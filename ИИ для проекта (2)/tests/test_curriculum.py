import tempfile
import threading
import unittest

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
