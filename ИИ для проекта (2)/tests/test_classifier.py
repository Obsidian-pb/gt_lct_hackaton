import copy
import unittest
from card_factory import CATALOG, SOURCE, generate, generation_options, validate_content
from card_fake import FactoryFake


class ClassifierTests(unittest.TestCase):
    def test_complete_source_and_distinct_water_cases(self):
        self.assertEqual(len(CATALOG), 1283)
        self.assertEqual(len(SOURCE['categories']), 24)
        self.assertEqual(len({x['id'] for x in CATALOG}), 1283)
        self.assertEqual(SOURCE['categories']['24'], 'БПЛА')
        water = {x['id']: x for x in generation_options({'category':'17', 'classification':{'sign1':'Человек в воде, на льдине'}})}
        self.assertEqual(water['17070200']['title'], 'Тонет человек')
        self.assertEqual(water['17070300']['title'], 'Утонул человек')
        self.assertEqual(water['17070500']['title'], 'Утопленник')
        self.assertEqual(water['17070500']['source_row'], 1122)

    def test_filtering_and_impossible_combination_before_model_call(self):
        provider = FactoryFake()
        request = {'category':'17', 'classification':{'sign1':'Человек в воде, на льдине', 'sign2':'Всплыл утопленник'}, 'flags':{'injured':'unknown'}, 'location':'Учебный город'}
        result = generate(provider, request)
        self.assertEqual(result['content']['class_ids'], ['17070500'])
        self.assertEqual(result['content']['flags']['injured'], 'unknown')
        self.assertEqual(provider.calls[-1][1]['incident_class']['id'], '17070500')
        calls = len(provider.calls)
        with self.assertRaises(ValueError):
            generate(provider, {**request, 'category':'1'})
        with self.assertRaises(ValueError):
            generate(provider, {**request, 'flags':{'injured':True}})
        self.assertEqual(len(provider.calls), calls)

    def test_conditional_service_values_are_preserved(self):
        entry = next(x for x in CATALOG if x['id']=='1010101')
        rules = {r['column']:r for r in entry['rules']}
        self.assertEqual(rules['Z']['service'], '103')
        self.assertEqual(rules['Z']['value'], 'нет реагирования')
        self.assertIn('не на месте', rules['Z']['condition'])
        self.assertEqual(rules['Y']['value'], 'пожар')

    def test_legacy_cards_remain_reviewable(self):
        content = generate(FactoryFake(), {'category':'fire'})['content']
        content.pop('flags')
        content['class_ids'] = ['demo-fire-balcony']
        original = copy.deepcopy(content)
        self.assertEqual(validate_content(content, approval=True), original)

    def test_ambiguous_main_service_is_not_selected_arbitrarily(self):
        entry = next(x for x in CATALOG if x['main_service_source']=='MOESK, OEK')
        self.assertEqual(entry['main_service'], '')
        self.assertEqual(entry['services'], ['MOESK','OEK'])
