from dataclasses import dataclass, field

import pytest

from tistory_growth_os.delivery.browser_signin import SignInState, connect_manager


@dataclass(frozen=True, slots=True)
class SignInSurface:
    states: list[SignInState]
    actions: list[SignInState] = field(default_factory=list)

    def observe(self) -> SignInState:
        return self.states.pop(0)

    def open_login(self) -> None:
        self.actions.append(SignInState.LOGIN)

    def choose_account(self) -> None:
        self.actions.append(SignInState.ACCOUNT)


def test_ready_manager_requires_no_login_action() -> None:
    surface = SignInSurface([SignInState.READY])
    assert connect_manager(surface) == SignInState.READY
    assert surface.actions == []


def test_normal_login_and_account_selection_reach_manager() -> None:
    surface = SignInSurface([SignInState.LOGIN, SignInState.ACCOUNT, SignInState.READY])
    assert connect_manager(surface) == SignInState.READY
    assert surface.actions == [SignInState.LOGIN, SignInState.ACCOUNT]


@pytest.mark.parametrize('state', [SignInState.OWNER_REQUIRED, SignInState.UNKNOWN])
def test_unrecognized_or_protected_page_never_receives_clicks(state: SignInState) -> None:
    surface = SignInSurface([state])
    assert connect_manager(surface) == state
    assert surface.actions == []


@pytest.mark.parametrize('state', [SignInState.LOGIN, SignInState.ACCOUNT])
def test_repeated_page_stops_without_repeated_action(state: SignInState) -> None:
    surface = SignInSurface([state, state])
    assert connect_manager(surface) == SignInState.UNKNOWN
    assert surface.actions == [state]


def test_backwards_transition_stops_without_clicking_login_again() -> None:
    surface = SignInSurface([SignInState.ACCOUNT, SignInState.LOGIN])
    assert connect_manager(surface) == SignInState.UNKNOWN
    assert surface.actions == [SignInState.ACCOUNT]
