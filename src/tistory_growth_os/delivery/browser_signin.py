from enum import StrEnum
from typing import Protocol, assert_never


class SignInState(StrEnum):
    READY = 'ready'
    LOGIN = 'login'
    ACCOUNT = 'account'
    OWNER_REQUIRED = 'owner_required'
    UNKNOWN = 'unknown'


class SignInSurface(Protocol):
    def observe(self) -> SignInState: ...
    def open_login(self) -> None: ...
    def choose_account(self) -> None: ...


def connect_manager(surface: SignInSurface) -> SignInState:
    attempted: set[SignInState] = set()
    for _ in range(3):
        state = surface.observe()
        match state:
            case SignInState.READY | SignInState.OWNER_REQUIRED | SignInState.UNKNOWN:
                return state
            case SignInState.LOGIN:
                if attempted:
                    return SignInState.UNKNOWN
                attempted.add(state)
                surface.open_login()
            case SignInState.ACCOUNT:
                if state in attempted:
                    return SignInState.UNKNOWN
                attempted.add(state)
                surface.choose_account()
            case _:
                assert_never(state)
    return SignInState.UNKNOWN
