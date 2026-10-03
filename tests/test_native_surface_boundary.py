from contextlib import closing
from datetime import datetime
from playwright.sync_api import sync_playwright
from tistory_growth_os.delivery.new_reservation_identity import NewReservationIntent
from tistory_growth_os.delivery.playwright_article_input import ArticleInput
from tistory_growth_os.delivery.playwright_native_surface import NativeSurface
from tistory_growth_os.delivery.reservation_readback import ReservationContent, ReservationMedia
from tistory_growth_os.domain.ids import MediaId


def test_native_surface_has_no_default_write_authority() -> None:
    media = tuple(ReservationMedia(MediaId(str(index)), '설명') for index in range(4))
    intent = NewReservationIntent(datetime.fromisoformat('2030-01-01T19:00:00+09:00'),
                                  ReservationContent('제목', 'a' * 64, media, MediaId('0'), '생활정보', '생활정보', ()), 'b' * 64)
    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        surface = NativeSurface(page, ArticleInput(intent, '', ()), lambda: False)
        assert surface.authorize(intent, datetime.now().astimezone()) == ('runtime_authority_required',)
        assert surface.save(intent) is None
        assert page.url == 'about:blank'
        assert not surface.prepared and not surface.save_attempted
