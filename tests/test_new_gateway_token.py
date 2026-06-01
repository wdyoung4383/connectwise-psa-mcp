"""Test the gateway-token minting helper."""

import hashlib


def test_mint_produces_consistent_hash():
    from scripts.new_gateway_token import mint

    token, token_hash = mint()
    assert isinstance(token, str) and len(token) >= 20
    assert token_hash == hashlib.sha256(token.encode()).hexdigest()


def test_mint_is_random():
    from scripts.new_gateway_token import mint

    assert mint()[0] != mint()[0]
