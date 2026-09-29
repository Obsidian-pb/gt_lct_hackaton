import tempfile
import threading
import unittest
from unittest.mock import patch

from ai_core import Engine
from card_fake import FactoryFake
import card_factory
import card_reference
import curriculum
import materials
from rest_api import RestAPI, APIError
from application import dispatch


class CurriculumFlow(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.engine = Engine(FactoryFake(), temp.name)
        source = card_factory.generate(self.engine.provider, {'topic': 'Учебный пожар', 'category': 'fire'})['content']
        source['fields']['phone_aon'] = '+7 (000) 111-22-33'
        caller = {'version': 1, 'phone_callback': '+7 (000) 444-55-66'}
        reference = card_reference.generate(self.engine.provider, {'content': source, 'caller_scenario': caller})
        published = dispatch(self.engine, 'card_publish', {'content': source, 'reference': reference,
            'caller_scenario': caller, 'teacher': 'Преподаватель', 'reference_checked': True})
        self.task_id = published['task_id']

    def create(self, participants=None):
        first = curriculum.save_scenario(self.engine, {'title':'Пожары', 'teacher':'Преподаватель', 'task_ids':[self.task_id]})
        curriculum.approve_scenario(self.engine, first['id'], 'Преподаватель')
        second = curriculum.save_scenario(self.engine, {'title':'Жилые дома', 'teacher':'Преподаватель', 'task_ids':[self.task_id]})
        curriculum.approve_scenario(self.engine, second['id'], 'Преподаватель')
        training = curriculum.save_training(self.engine, {'title':'Занятие', 'teacher':'Преподаватель',
            'scenario_ids':[first['id'],second['id']], 'seconds':30,
            'participants':participants or [{'student':'Оператор','role':'operator'},
                {'student':'ДДС','role':'dds'}, {'student':'Пожарная','role':'service','service':'101'},
                {'student':'Медицина','role':'service','service':'103'}]})
        return curriculum.activate(self.engine, training['id'])

    def test_service_deadlines_call_and_exact_house_route(self):
        active = self.create()
        record = active['cards'][0]
        card = dict(self.engine.load(record['operator_session_id'])['card'])
        card.update(city='Железногорск', street='улица Королёва', house='7А',
                    _report='Дым из окна жилого дома')
        record.update(card=card, status='service_review', services=['101'],
                      routed_at=curriculum.now())
        curriculum._write(self.engine, active)
        rest = RestAPI(self.engine, threading.Lock())
        base = f"/api/v1/trainings/{active['id']}/cards/{record['id']}"
        with self.assertRaises(APIError):
            rest.handle('POST', base+'/actions', {'student':'Пожарная','status':'accepted','text':'Принято'})
        opened = rest.handle('POST', base+'/opens', {'student':'Пожарная'}).data
        self.assertIn('opened_at', opened)
        with self.assertRaises(APIError):
            rest.handle('POST', base+'/opens', {'student':'Медицина'})
        rest.handle('POST', base+'/actions', {'student':'Пожарная','status':'accepted','text':'Наряд назначен'})
        current = curriculum.desk(self.engine, 'Пожарная')[0]['cards'][0]
        self.assertEqual(current['service_progress']['101']['entries'][0]['text'], 'Наряд назначен')
        route = rest.handle('GET', base+'/route?student=%D0%9F%D0%BE%D0%B6%D0%B0%D1%80%D0%BD%D0%B0%D1%8F').data
        self.assertTrue(route['found'])
        self.assertEqual(route['destination']['label'], 'улица Королёва, 7А')
        self.assertEqual(route['points'][-1], route['destination']['point'])
        with self.assertRaises(APIError):
            rest.handle('POST', base+'/actions', {'student':'Пожарная','text':'Выезд подтверждён'})
        with self.assertRaises(APIError):
            rest.handle('GET', base+'/route?student=%D0%9C%D0%B5%D0%B4%D0%B8%D1%86%D0%B8%D0%BD%D0%B0')
        rest.handle('POST', base+'/senior-call/answer', {'student':'Пожарная'})
        rest.handle('POST', base+'/actions', {'student':'Пожарная','text':'Выезд подтверждён'})
        self.assertEqual(curriculum.get(self.engine, active['id'])['cards'][0]['status'], 'done')

    def test_main_create_training_from_cards_or_categories(self):
        rest=RestAPI(self.engine,threading.Lock())
        dashboard=rest.handle('GET','/api/v1/teacher/dashboard').data
        selected=next(t for t in dashboard['tasks'] if t['id']==self.task_id)
        self.assertIn('1',selected['category_ids'])
        base={'title':'Прямая тренировка','teacher':'Преподаватель','participants':[]}
        chosen=rest.handle('POST','/api/v1/trainings',{**base,'task_ids':[self.task_id]}).data
        self.assertEqual(chosen['selection_mode'],'cards')
        self.assertEqual(chosen['task_ids'],[self.task_id])
        self.assertEqual(curriculum.lobby(self.engine,chosen['id'])['card_count'],1)
        category=rest.handle('POST','/api/v1/trainings',{**base,'categories':['1']}).data
        self.assertEqual(category['selection_mode'],'categories')
        self.assertIn(self.task_id,category['task_ids'])
        self.assertEqual(curriculum.lobby(self.engine,category['id'])['card_count'],1)
        for training in (chosen,category):
            room=curriculum.add_participants(self.engine,training['id'],'Преподаватель',['Алексей Иванов','Мария Петрова'])
            for participant,role in zip(room['participants'],['operator','dds']):
                curriculum.assign_role(self.engine,training['id'],participant['id'],'Преподаватель',role)
            active=curriculum.activate(self.engine,training['id'])
            self.assertEqual(len(active['cards']),1)
            self.assertEqual(active['cards'][0]['task_id'],self.task_id)
        with self.assertRaises(APIError):
            rest.handle('POST','/api/v1/trainings',{**base,'categories':['999']})
        with self.assertRaises(APIError):
            rest.handle('POST','/api/v1/trainings',{**base,'categories':['22']})
        with self.assertRaises(APIError):
            rest.handle('POST','/api/v1/trainings',{**base,'task_ids':[self.task_id],'categories':['1']})

    def test_teacher_adds_demo_learners_to_waiting_room(self):
        scenario=curriculum.save_scenario(self.engine,{'title':'Пожар','teacher':'Преподаватель','task_ids':[self.task_id]})
        curriculum.approve_scenario(self.engine,scenario['id'],'Преподаватель')
        training=curriculum.save_training(self.engine,{'title':'Группа','teacher':'Преподаватель','scenario_ids':[scenario['id']]})
        route=f"/api/v1/trainings/{training['id']}/lobby/participants"
        rest=RestAPI(self.engine,threading.Lock())
        names=['Алексей Иванов','Мария Петрова','Дмитрий Соколов','Анна Кузнецова']
        first=rest.handle('POST',route,{'teacher':'Преподаватель','students':names}).data
        self.assertEqual([p['student'] for p in first['participants']],names)
        self.assertTrue(all(p['role']=='waiting' and p['id'] for p in first['participants']))
        again=rest.handle('POST',route,{'teacher':'Преподаватель','students':names}).data
        self.assertEqual([p['id'] for p in again['participants']],[p['id'] for p in first['participants']])
        curriculum.join_lobby(self.engine,training['id'],names[0])
        self.assertEqual(len(curriculum.lobby(self.engine,training['id'])['participants']),4)
        with self.assertRaises(ValueError):
            curriculum.add_participants(self.engine,training['id'],'Не преподаватель',['Пятый Участник'])
        with self.assertRaises(ValueError):
            curriculum.add_participants(self.engine,training['id'],'Преподаватель',['Одинаковое Имя','одинаковое имя'])
        roles=['operator','dds','service','service']
        for person,role in zip(first['participants'],roles):
            curriculum.assign_role(self.engine,training['id'],person['id'],'Преподаватель',role,'101' if role=='service' else '')
        curriculum.activate(self.engine,training['id'])
        with self.assertRaises(ValueError):
            curriculum.add_participants(self.engine,training['id'],'Преподаватель',['Поздний Участник'])

    def test_admin_style_role_change_can_switch_participant_to_dispatcher_before_start(self):
        scenario=curriculum.save_scenario(self.engine,{'title':'Роли','teacher':'Преподаватель','task_ids':[self.task_id]})
        curriculum.approve_scenario(self.engine,scenario['id'],'Преподаватель')
        training=curriculum.save_training(self.engine,{'title':'Смена роли','teacher':'Преподаватель','scenario_ids':[scenario['id']],
            'participants':[{'student':'Глеб Шамсудинов','role':'operator'},{'student':'Второй Участник','role':'dds'}]})
        me=next(p for p in training['participants'] if p['student']=='Глеб Шамсудинов')
        other=next(p for p in training['participants'] if p['student']=='Второй Участник')
        curriculum.assign_role(self.engine,training['id'],me['id'],'Преподаватель','dds')
        curriculum.assign_role(self.engine,training['id'],other['id'],'Преподаватель','operator')
        changed=curriculum.get(self.engine,training['id'])
        self.assertEqual(next(p for p in changed['participants'] if p['student']=='Глеб Шамсудинов')['role'],'dds')
        active=curriculum.activate(self.engine,training['id'])
        self.assertEqual(curriculum.desk(self.engine,'Глеб Шамсудинов')[0]['role'],'dds')
        self.assertEqual(active['status'],'active')

    def test_dispatcher_can_generate_four_ai_reference_cards_for_self_practice(self):
        active = self.create()
        result = curriculum.generate_dispatcher_examples(self.engine, active['id'], 'ДДС', 4,
            'Разные учебные происшествия', 'Учебный город')
        self.assertEqual(result['created'], 4)
        desk = curriculum.desk(self.engine, 'ДДС')[0]
        self.assertEqual(len(desk['cards']), 4)
        self.assertTrue(all(card['ai_demo'] for card in desk['cards']))
        self.assertTrue(all(card['student'] == 'ИИ · эталонный оператор' for card in desk['cards']))
        self.assertTrue(all(card['card']['_report'] for card in desk['cards']))
        self.assertTrue(all(card['card']['city'] == 'Железногорск' and
                            card['card']['region'] == 'Красноярский край' for card in desk['cards']))
        self.assertTrue(all(card['card']['phone_callback'].startswith('+7 (000) ') for card in desk['cards']))
        self.assertTrue(all('_incident_source' not in card and '_caller_scenario' not in card for card in desk['cards']))
        stored = curriculum.get(self.engine, active['id'])
        generated = [card for card in stored['cards'] if card.get('ai_demo')]
        self.assertEqual(len(generated), 4)
        self.assertTrue(all(card.get('_incident_source') and card.get('_caller_scenario') for card in generated))
        first = desk['cards'][0]
        call = curriculum.dial_callback(self.engine, active['id'], first['id'], 'ДДС', first['card']['phone_callback'])
        with patch('dialogue_gateway.ask', return_value={'reply':'Адрес подтверждаю.','callback_disclosed':False}):
            answer = curriculum.callback(self.engine, active['id'], first['id'], 'ДДС', 'Адрес верный?', call_id=call['id'])
        self.assertEqual(answer['reply'], 'Адрес подтверждаю.')
        routed = curriculum.route_card(self.engine, active['id'], first['id'], 'ДДС', ['101'], {})
        self.assertIn(next(card for card in routed['cards'] if card['id'] == first['id'])['status'], ('done','service_review'))

    def test_dispatcher_ai_examples_require_active_dds_and_limit_batch_to_four(self):
        active = self.create()
        with self.assertRaises(ValueError):
            curriculum.generate_dispatcher_examples(self.engine, active['id'], 'Оператор', 1)
        with self.assertRaises(ValueError):
            curriculum.generate_dispatcher_examples(self.engine, active['id'], 'ДДС', 5)
        rest = RestAPI(self.engine, threading.Lock())
        response = rest.handle('POST', f"/api/v1/trainings/{active['id']}/dispatcher-examples",
            {'student':'ДДС','count':2,'location':'Учебный город'}).data
        self.assertEqual(response['created'], 2)
        with self.assertRaises(APIError):
            rest.handle('POST', f"/api/v1/trainings/{active['id']}/dispatcher-examples",
                {'student':'ДДС','count':5,'location':'Учебный город'})

    def test_lobby_handoff_callback(self):
        scenario=curriculum.save_scenario(self.engine,{'title':'Пожар','teacher':'Преподаватель','task_ids':[self.task_id]})
        curriculum.approve_scenario(self.engine,scenario['id'],'Преподаватель')
        rest=RestAPI(self.engine,threading.Lock())
        created=rest.handle('POST','/api/v1/trainings',{'title':'Совместный вызов','teacher':'Преподаватель','scenario_ids':[scenario['id']]})
        training=created.data
        self.assertEqual(created.headers['Location'],'/api/v1/trainings/'+training['id'])
        self.assertEqual(rest.handle('GET','/api/v1/rooms/'+training['room_code']).data['id'],training['id'])
        with self.assertRaises(ValueError): curriculum.activate(self.engine,training['id'])
        for name,role in [('Иванов Оператор','operator'),('Петров Диспетчер','dds')]:
            joined=rest.handle('POST','/api/v1/trainings/'+training['id']+'/lobby/joins',{'student':name}).data
            person=next(p for p in joined['participants'] if p['student']==name)
            rest.handle('PUT','/api/v1/trainings/'+training['id']+'/lobby/participants/'+person['id'],{'teacher':'Преподаватель','role':role})
        active=curriculum.activate(self.engine,training['id'])
        session_id=active['cards'][0]['operator_session_id']
        self.assertTrue(self.engine.load(session_id)['training']['handoff_to_dds'])
        dispatch(self.engine,'student_action',{'student':'Иванов Оператор','id':session_id,'operation':'accept'})
        card=dict(self.engine.load(session_id)['card']);card['_report']='Дым из окна'
        dispatch(self.engine,'student_action',{'student':'Иванов Оператор','id':session_id,'operation':'submit','card':card})
        record=curriculum.desk(self.engine,'Петров Диспетчер')[0]['cards'][0]
        base=f"/api/v1/trainings/{training['id']}/cards/{record['id']}"
        phone=record['card'].get('phone_callback') or record['card']['phone_aon']
        with patch('dialogue_gateway.ask',return_value={'reply':'Двое на этаже.','callback_disclosed':False}) as ai:
            with self.assertRaises(APIError):
                rest.handle('POST',base+'/callbacks',{'student':'Петров Диспетчер','question':'Сколько людей?','call_id':'000000000000'})
            with self.assertRaises(APIError):
                rest.handle('POST',base+'/calls',{'student':'Петров Диспетчер','number':'+7 (000) 999-99-99'})
            self.assertEqual(ai.call_count,0)
            call=rest.handle('POST',base+'/calls',{'student':'Петров Диспетчер','number':phone}).data
            answer=rest.handle('POST',base+'/callbacks',{'student':'Петров Диспетчер','question':'Сколько людей?','call_id':call['id']}).data
            rest.handle('POST',base+'/calls/'+call['id']+'/hangup',{'student':'Петров Диспетчер'})
            with self.assertRaises(APIError):
                rest.handle('POST',base+'/callbacks',{'student':'Петров Диспетчер','question':'Повторите','call_id':call['id']})
            self.assertEqual(ai.call_count,1)
        self.assertEqual(answer['reply'],'Двое на этаже.')
        self.assertEqual(len(curriculum.desk(self.engine,'Петров Диспетчер')[0]['cards'][0]['callback_turns']),2)
        with self.assertRaises(ValueError):curriculum.route_card(self.engine,training['id'],record['id'],'Петров Диспетчер',['101'],{'phone_aon':'подмена'})
        second=rest.handle('POST',base+'/calls',{'student':'Петров Диспетчер','number':phone}).data
        routed=curriculum.route_card(self.engine,training['id'],record['id'],'Петров Диспетчер',['101','103'],{'people':'2'},'101')
        self.assertEqual(routed['cards'][0]['status'],'done')
        self.assertEqual(routed['cards'][0]['callback_call']['id'],second['id'])
        self.assertEqual(routed['cards'][0]['callback_call']['status'],'ended')
        self.assertEqual(routed['cards'][0]['card']['_main_service'],'101')

    def test_full_card_lifecycle_and_service_isolation(self):
        training = self.create()
        self.assertEqual(len(training['cards']), 1, 'Shared task appears only once across scenarios')
        session_id = training['cards'][0]['operator_session_id']
        session = self.engine.load(session_id)
        self.assertEqual(session['status'], 'awaiting_call')
        self.assertIsNone(session['activated_at'])
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'student_action', {'student':'Оператор','id':session_id,'operation':'ask','question':'Адрес?'})
        dispatch(self.engine, 'student_action', {'student':'Оператор','id':session_id,'operation':'accept'})
        session = self.engine.load(session_id)
        self.assertIsNotNone(session['activated_at'])
        card = dict(session['card'])
        card.update(_report='Горит дом', _services='["101"]', _main_service='101')
        submitted = dispatch(self.engine, 'student_action', {'student':'Оператор','id':session_id,'operation':'submit','card':card})
        self.assertTrue(submitted['scenario_complete'])
        self.assertIsNotNone(self.engine.load(session_id)['machine_assessment'])
        self.assertEqual(len(curriculum.desk(self.engine,'ДДС')[0]['cards']), 1)
        self.assertEqual(curriculum.desk(self.engine,'Медицина')[0]['cards'], [])
        card_id=training['cards'][0]['id']
        with self.assertRaises(ValueError):
            curriculum.route_card(self.engine,training['id'],card_id,'Оператор',['101'],{})
        curriculum.route_card(self.engine,training['id'],card_id,'ДДС',['101'],{'_report':'Пожар, уточнён адрес'})
        self.assertEqual(len(curriculum.desk(self.engine,'Пожарная')[0]['cards']), 1)
        self.assertEqual(curriculum.desk(self.engine,'Медицина')[0]['cards'], [])
        with self.assertRaises(ValueError):
            curriculum.service_action(self.engine, training['id'],card_id,'Медицина','Наряд')
        curriculum.service_action(self.engine, training['id'],card_id,'Пожарная','Направлен расчёт')
        self.assertEqual(curriculum.get(self.engine,training['id'])['cards'][0]['status'],'done')

    def test_112_call_is_answered_before_dialogue_or_card(self):
        training=self.create([{'student':'Курсант','role':'operator'}])
        session_id=training['cards'][0]['operator_session_id']
        waiting=dispatch(self.engine,'student_action',{'student':'Курсант','id':session_id,
            'operation':'student','full_form':True})
        self.assertEqual(waiting['status'],'awaiting_call')
        self.assertEqual(waiting['history'],[])
        self.assertIsNone(waiting['activated_at'])
        with self.assertRaises(ValueError):
            dispatch(self.engine,'student_action',{'student':'Курсант','id':session_id,
                'operation':'ask','question':'Служба 112, слушаю вас'})
        accepted=dispatch(self.engine,'student_action',{'student':'Курсант','id':session_id,
            'operation':'accept','full_form':True})
        self.assertEqual(accepted['status'],'active')
        self.assertEqual(accepted['history'][0]['role'],'caller')
        if accepted['call_intro']=='greeting':
            self.assertEqual(accepted['history'][0]['text'],'Алло, алло, это 112?')
        else:
            self.assertEqual(accepted['history'][0]['text'],self.engine.load(self.task_id)['opening'])
        with self.assertRaises(ValueError):
            dispatch(self.engine,'student_action',{'student':'Курсант','id':session_id,
                'operation':'accept'})

    def test_dds_receives_senior_call_and_exact_house_route_after_routing(self):
        training = self.create()
        record = training['cards'][0]
        session_id = record['operator_session_id']
        dispatch(self.engine, 'student_action', {'student':'Оператор','id':session_id,'operation':'accept'})
        card = dict(self.engine.load(session_id)['card'])
        card['_report'] = 'Дым из окна жилого дома'
        dispatch(self.engine, 'student_action', {'student':'Оператор','id':session_id,
            'operation':'submit','card':card})
        rest = RestAPI(self.engine, threading.Lock())
        base = f"/api/v1/trainings/{training['id']}/cards/{record['id']}"
        rest.handle('POST',base+'/routing',{'student':'ДДС','services':['101','103'],
            'updates':{'city':'Железногорск','street':'улица Королёва','house':'7А',
                       'address_text':'Железногорск, улица Королёва, 7А'}})
        desk = curriculum.desk(self.engine,'ДДС')[0]
        self.assertEqual(desk['cards'], [])
        self.assertEqual(len(desk['routed_cards']), 1)
        self.assertEqual(desk['routed_cards'][0]['dds_senior_calls']['101']['status'],'ringing')
        with self.assertRaises(APIError):
            rest.handle('GET',base+'/dds-routes/101?student=ДДС')
        with self.assertRaises(APIError):
            rest.handle('POST',base+'/dds-senior-calls/101/answer',{'student':'Оператор'})
        answer=rest.handle('POST',base+'/dds-senior-calls/101/answer',{'student':'ДДС'}).data
        self.assertEqual(answer['status'],'answered')
        self.assertEqual(rest.handle('POST',base+'/dds-senior-calls/101/answer',{'student':'ДДС'}).data['answered_at'],answer['answered_at'])
        route=rest.handle('GET',base+'/dds-routes/101?student=ДДС').data
        self.assertTrue(route['found'])
        self.assertEqual(route['destination']['label'],'улица Королёва, 7А')
        self.assertNotEqual(route['origin']['point'],route['destination']['point'])
        with self.assertRaises(APIError):
            rest.handle('GET',base+'/dds-routes/103?student=ДДС')

    def test_existing_operator_session_answers_without_losing_card(self):
        old=self.engine.start(self.task_id, 'Курсант')
        self.assertEqual(old['status'],'active')
        self.assertIsNone(old.get('activated_at'))
        accepted=dispatch(self.engine,'student_action',{'student':'Курсант','id':old['id'],
            'operation':'accept','full_form':True})
        self.assertEqual(accepted['status'],'active')
        self.assertIsNotNone(accepted['activated_at'])
        self.assertIsNotNone(accepted['call_answered_at'])
        self.assertEqual(accepted['card']['external_number'],old['card']['external_number'])
        self.assertEqual(len(accepted['history']),1)
        with self.assertRaises(ValueError):
            dispatch(self.engine,'student_action',{'student':'Курсант','id':old['id'],
                'operation':'accept'})

    def test_http_contract_accept_and_manual_teacher_grade(self):
        training=self.create([{'student':'Курсант','role':'operator'}])
        router=RestAPI(self.engine, threading.Lock())
        session_id=training['cards'][0]['operator_session_id']
        response=router.handle('POST',f'/api/v1/students/Курсант/sessions/{session_id}/acceptance',{})
        self.assertEqual(response.data['status'],'active')
        session=self.engine.load(session_id)
        session['status']='submitted';session['submitted_at']=session['activated_at'];self.engine.save(session)
        decisions={key:'Проверено преподавателем' for key in session['task']['fields']}
        result=router.handle('PUT',f'/api/v1/works/{session_id}/percentage-decision',
                             {'teacher':'Преподаватель','percent':72,'conclusion':'Карточка проверена','decisions':decisions})
        self.assertEqual(result.data['percent'],72)
        with self.assertRaises(APIError):
            router.handle('POST',f'/api/v1/students/Курсант/sessions/{session_id}/acceptance',{})

    def test_adaptive_next_card_uses_previous_score_and_task_levels(self):
        ids=[]
        for _ in range(3):
            t=self.engine.sample()
            self.engine.approve(t['id'],'Преподаватель')
            ids.append(t['id'])
        scenario=curriculum.save_scenario(self.engine,{'title':'Разные уровни','teacher':'Преподаватель',
            'task_ids':ids,'task_difficulties':dict(zip(ids,[3,1,5]))})
        curriculum.approve_scenario(self.engine,scenario['id'],'Преподаватель')
        plan=curriculum.save_training(self.engine,{'title':'Адаптивная','teacher':'Преподаватель',
            'scenario_ids':[scenario['id']],'difficulty':'adaptive',
            'participants':[{'student':'Курсант','role':'operator'}]})
        active=curriculum.activate(self.engine,plan['id'])
        first=next(s for s in self.engine.list_items('s') if s['status']=='awaiting_call')
        curriculum.accept_call(self.engine,first)
        self.engine.submit(first['id'])  # Unfilled card: 0% machine match.
        from training_progress import advance
        second=advance(self.engine,first['id'])
        self.assertEqual(self.engine.load(second['next_id'])['training']['task_difficulty'],1)
        curriculum.accept_call(self.engine,self.engine.load(second['next_id']))
        later=self.engine.load(second['next_id'])
        later['status']='submitted';later['machine_assessment']={'percent':100};self.engine.save(later)
        third=advance(self.engine,later['id'])
        self.assertEqual(self.engine.load(third['next_id'])['training']['task_difficulty'],5)

    def test_reading_material_persists_and_rejects_unsafe_url(self):
        entry=materials.add(self.engine,{'title':'Инструкция АРМ 112','url':'https://example.org/manual.pdf','teacher':'Преподаватель'})
        self.assertEqual(materials.items(self.engine)[0]['id'],entry['id'])
        with self.assertRaises(ValueError):
            materials.add(self.engine,{'title':'Файл','url':'file:///etc/passwd','teacher':'Преподаватель'})


if __name__ == '__main__':
    unittest.main()
