import copy
import unittest

from card_factory import GENERATED, approve, generate, osm_addresses
from card_reference import validate_reference
from card_fake import response


class OSMCardsTests(unittest.TestCase):
    def setUp(self):
        self.index, self.houses = osm_addresses()
        self.house = self.houses[0]
        self.location = f"{self.index['city']}, {self.index['region']}"

    def request(self):
        return {'category':'fire', 'location':self.location, 'osm_address_id':self.house['id']}

    def test_uses_exact_house_city_and_point_from_osm(self):
        house, index = self.house, self.index
        class Provider:
            model = 'test'
            def generate(self, prompt, payload, **kwargs):
                result = response()
                result['fields'].update(country=index['country'],region=index['region'],city=index['city'],
                                        street=house['street'],house=house['house'])
                result['report'] = f"Я по адресу {house['street']}, дом {house['house']}. В гараже дым."
                return result
        generated = generate(Provider(), self.request())
        fields = generated['content']['fields']
        self.assertEqual((fields['region'],fields['city'],fields['street'],fields['house']),
                         (index['region'],index['city'],house['street'],house['house']))
        self.assertEqual([float(fields['longitude']),float(fields['latitude'])],house['point'])
        self.assertEqual(generated['osm_address']['id'],house['id'])

    def test_wrong_region_or_invented_street_is_rejected(self):
        class Wrong:
            def generate(self, prompt, payload, **kwargs):
                result = response()
                result['fields']['region'] = 'Курская область'
                return result
        with self.assertRaisesRegex(ValueError, 'OSM'):
            generate(Wrong(), self.request())
        with self.assertRaisesRegex(ValueError, 'справочника OSM'):
            generate(Wrong(), {**self.request(), 'osm_address_id':'nonexistent'})

    def test_generated_card_is_its_own_reference_without_second_model_call(self):
        class Provider:
            def generate(self, prompt, payload, **kwargs):
                result = response()
                result['fields'].update(country=self_index['country'],region=self_index['region'],city=self_index['city'],
                                        street=self_house['street'],house=self_house['house'])
                result['report'] = f"Я по адресу {self_house['street']}, дом {self_house['house']}. Дым из гаража."
                return result
        self_house, self_index = self.house, self.index
        content = generate(Provider(), self.request())['content']
        expected = {k: {'value':content['fields'][k].strip() or 'Неизвестно','evidence':''} for k in GENERATED}
        reference = {'version':2,'origin':'generated-card','source_content':copy.deepcopy(content),
                     'source_scenario':None,'answer':{'expected_fields':expected,'summary':'Дым из гаража',
                     'classification_reason':'Указан тип происшествия','services_reason':'Указана служба',
                     'questions':[],'critical_errors':['Не искажать адрес.']}}
        self.assertEqual(validate_reference(reference,content)['answer']['expected_fields'],expected)
        self.assertEqual(approve({'content':content,'reference':reference,'teacher':'Преподаватель',
                                  'reference_checked':True})['reference']['version'],2)
        reference['answer']['expected_fields']['city']['value']='Курск'
        with self.assertRaisesRegex(ValueError,'совпадать'):
            validate_reference(reference,content)


if __name__ == '__main__':
    unittest.main()
