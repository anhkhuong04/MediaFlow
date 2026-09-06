import socket

import pytest
from pytest_socket import SocketBlockedError


def test_default_suite_blocks_network_sockets() -> None:
    with pytest.warns(UserWarning, match="socket.socket"), pytest.raises(SocketBlockedError):
        socket.socket()
