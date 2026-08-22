import pytest

from src.dialer.exotel import ExotelProvider
from src.dialer.plivo import PlivoProvider
from src.dialer.provider import TelephonyProvider


def test_exotel_provider_is_a_telephony_provider_and_raises_not_implemented():
    provider = ExotelProvider(
        account_sid="sid", api_key="key", api_token="token",
        subdomain="api.exotel.com", exophone="+91XXXXXXXXXX",
    )
    assert isinstance(provider, TelephonyProvider)
    with pytest.raises(NotImplementedError):
        provider.place_call("+919999999999")


def test_plivo_provider_is_a_telephony_provider_and_raises_not_implemented():
    provider = PlivoProvider(auth_id="id", auth_token="token", from_number="91XXXXXXXXXX")
    assert isinstance(provider, TelephonyProvider)
    with pytest.raises(NotImplementedError):
        provider.place_call("+919999999999")
