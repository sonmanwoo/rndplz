"""P1: a full resume keeps its rows and whole titles, a row's title heads its card line, and direct
liquid cooling and legged inspection robots reach their research-map capabilities."""
import subprocess
import unittest
from pathlib import Path

from rndplz.people_map import build_capabilities
from rndplz.person_cards import PersonCards
from rndplz.profile_reading import CAREER_TITLE, DIGEST_CAREERS, digest_contract_spec, finish_digest
from tests.test_person_card import public_engine

CARD = {'name': '시험인물', 'organization': '', 'role': '', 'bio': '', 'skills': [], 'interests': [], 'careers': []}
ROOT = Path(__file__).resolve().parents[1]


class ProfileP1Tests(unittest.TestCase):
    def test_contract_allows_a_full_resume(self):
        careers = digest_contract_spec()['format']['properties']['careers']
        self.assertEqual((careers['maxItems'], careers['items']['properties']['title']['maxLength']), (DIGEST_CAREERS, CAREER_TITLE))

    def test_resume_keeps_ten_rows_whole_titles_and_author_order(self):
        long_title = ('Highly energy-efficient manifold microchannel for cooling electronics with a coefficient '
                      'of performance over one hundred thousand in data centers')
        self.assertGreater(len(long_title), 120)
        rows = [{'title': '과제 ' + chr(0xAC00 + i), 'organization': '', 'period': '', 'role': '',
                 'description': '과제 ' + chr(0xAC00 + i) + ' 설명'} for i in range(12)]
        rows[0] = {'title': long_title, 'organization': '', 'period': '', 'role': '제1저자', 'description': '학술지 논문'}
        text = ' '.join(row['title'] + ' ' + row['description'] for row in rows) + ' 제1저자'
        careers = finish_digest({'careers': rows}, text, CARD)['careers']
        self.assertEqual(len(careers), DIGEST_CAREERS)
        self.assertEqual(careers[0]['title'], long_title)  # no longer cut at 120
        self.assertEqual(careers[0]['role'], '제1저자')  # an author order is a role
        numbered = finish_digest({'careers': [{**rows[1], 'role': '책임 (C18408)'}]}, text + ' 책임 (C18408)', CARD)
        self.assertEqual(numbered['careers'][0]['role'], '')  # an employee number is not

    def test_titled_rows_head_card_lines_and_reach_cooling_and_robotics(self):
        engine = public_engine()
        cards = PersonCards(engine.corpus)
        seed = cards.values('LOCAL-MANWOO')
        rows = [{'id': 'p1cooling000001', 'title': '전자장치 직접 액체 냉각 시험', 'organization': '시험 연구소', 'period': '2024',
                 'role': '', 'description': '콜드플레이트 열성능을 평가했다.'},
                {'id': 'p1robotics00001', 'title': '사족 보행 점검 로봇 실증', 'organization': '시험 연구소', 'period': '2023',
                 'role': '', 'description': '보행 로봇으로 설비를 점검했다.'}]
        cards.apply('LOCAL-MANWOO', {'fields': seed['fields'], 'careers': seed['careers'] + rows})
        timeline = engine.corpus.people['LOCAL-MANWOO'].profile['timeline']
        self.assertEqual([entry.get('title') for entry in timeline[-2:]], [row['title'] for row in rows])
        linked = {cap['id']: {p['id'] for p in cap['people']} for cap in build_capabilities(engine.corpus)}
        self.assertIn('LOCAL-MANWOO', linked['cooling'])
        self.assertIn('LOCAL-MANWOO', linked['robotics'])

    def test_card_line_shows_its_title_once(self):
        script = (
            "const v=require('./rndplz/web/person-view.js');"
            "const person={id:'P',name:'이름',profile:{curated:true,timeline:["
            "{date:'2024',title:'직접 액체 냉각 시험',text:'시험 연구소. 콜드플레이트 열성능을 평가했다.'},"
            "{date:'2023',title:'같은 제목',text:'같은 제목을 이미 담은 설명'},"
            "{date:'2022',text:'제목 없는 기존 줄'}]}};"
            "const html=v.render(person,{});"
            "if(!html.includes('<b class=\"timeline-title\">직접 액체 냉각 시험</b>'))throw new Error('title missing');"
            "if(html.includes('<b class=\"timeline-title\">같은 제목</b>'))throw new Error('title repeated');"
            "if(!html.includes('제목 없는 기존 줄'))throw new Error('untitled line lost');")
        subprocess.run(['node', '-e', script], cwd=ROOT, check=True)


if __name__ == '__main__':
    unittest.main()
