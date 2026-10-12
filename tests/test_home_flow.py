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

if __name__ == '__main__':
    unittest.main()
