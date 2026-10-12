"""Home flow (2026-10-12): a visitor's 로그인 pill in the header, the home receding on scroll, the move into the conversation."""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'rndplz' / 'web'


def read(name):
    return (WEB / name).read_text(encoding='utf-8')


class HeaderLoginPillTest(unittest.TestCase):
    def test_visitor_sees_login_pill_and_account_keeps_icon(self):
        menu = read('account-menu.js')
        self.assertIn("if(visitor){toggle.textContent='로그인';return;}", menu)
        self.assertIn("accountIcon(value.authenticated?account:null,!value.authenticated);", menu)
        # The last answer decides the first look, so a signed-in account does not flash the pill on load.
        self.assertIn("if(lastLook!=='account')accountIcon(null,true);", menu)
        self.assertIn("localStorage.setItem('rndplz.account.look',value.authenticated?'account':'visitor')", menu)

    def test_pill_matches_the_home_closing_button(self):
        pill = re.search(r'\.home-landing \.landing-pill \{([^}]*)\}', read('landing.css'))[1]
        header = re.search(r'#accountToggle\.is-login\{([^}]*)\}', read('site-cosmos.css'))[1]
        for declaration in ('border-radius:999px', 'background:#eeece9', 'font:600 14px'):
            self.assertIn(declaration, pill)
            self.assertIn(declaration, header)


class HomeRecedesOnScrollTest(unittest.TestCase):
    def test_landing_boot_fades_the_home_with_a_phone_keyboard_guard(self):
        boot = read('landing-boot.js')
        self.assertIn("addEventListener('scroll', schedule, {passive:true})", boot)
        self.assertIn("!(touch.matches && document.activeElement === message)", boot)
        # Motion off keeps only the fade.
        self.assertIn("node.style.transform = p && !quiet() ?", boot)


class EnterConversationTest(unittest.TestCase):
    def test_first_send_moves_through_a_view_transition(self):
        chat = read('chat.js')
        self.assertIn('await enterChat();let accepted=false', chat)
        self.assertIn('if($("main").className!=="welcome"||!document.startViewTransition||document.body.classList.contains("no-motion")', chat)

    def test_names_exist_only_during_the_move_and_never_on_a_replaced_message(self):
        css = read('home-cosmos.css')
        names = re.findall(r'^([^{}\n]*)\{view-transition-name:', css, re.M)
        self.assertGreaterEqual(len(names), 5)
        for selector in names:
            self.assertTrue(selector.strip().startswith('.home-to-chat '), selector)
            # render() replaces messages; a named one leaving the page cancels the whole move.
            self.assertNotIn('.message', selector)



class HomeSpiralFacesTest(unittest.TestCase):
    def test_every_face_on_screen_is_a_different_person(self):
        js = read('home-cosmos.js')
        # The field's few people no longer fill half the cards.
        self.assertNotIn('mine[i % mine.length]', js)
        # A card coming into view takes the next person not on screen, never one beside the heading.
        self.assertIn("const taken = new Set(inTitle), fresh = [];", js)
        self.assertIn("const id = order.find(person => !taken.has(person)) || null;", js)
        # A screen that would show more cards than people spaces them out.
        self.assertIn("Math.floor(crowd * .9 / Math.max(seen / samples, 1e-3))", js)


class HomeOpeningTest(unittest.TestCase):
    def test_opening_is_decided_before_the_first_paint_and_plays_on_the_home(self):
        html = read('index.html')
        # A blocking head script (no defer) right after theme.js, and the stage the opening plays on.
        self.assertIn('<script src="/theme.js"></script><script src="/home-intro-gate.js"></script>', html)
        self.assertIn('<div id="homeIntro" class="home-intro-stage" aria-hidden="true"></div>', html)
        self.assertNotIn('home-intro-word', html)  # the old re·search opening is gone
        css = read('home-cosmos.css')
        self.assertIn('html[data-home-intro] .home-intro-stage{display:block;position:fixed;inset:0;z-index:300', css)
        self.assertIn('body.home-welcome .home-whirl{display:none}', css)
        js = read('home-cosmos.js')
        self.assertIn("const TEAM = ['LOCAL-JINHO', 'LOCAL-MANWOO', 'LOCAL-DASOL', 'LOCAL-HONG'];", js)
        self.assertIn("localStorage.setItem('rndplz.intro.day', new Date().toLocaleDateString('sv-SE'))", js)
        self.assertIn('const SPIRAL = false;', js)
        self.assertIn("if (SPIRAL) run(home);", js)

    def test_gate_is_served(self):
        from rndplz.public_web import STATIC_FILES
        self.assertEqual(STATIC_FILES['/home-intro-gate.js'][0], 'home-intro-gate.js')

if __name__ == '__main__':
    unittest.main()
