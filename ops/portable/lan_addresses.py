"""Адреса этого компьютера в локальной сети — для учеников в классе.

Вызывается из start.cmd, когда сервер открыт наружу (WEB_HOST=0.0.0.0).
Печатает готовые ссылки: их диктуют или пишут на доске.
"""

import socket
import sys

port = sys.argv[1] if len(sys.argv) > 1 else "8090"
addresses: set[str] = set()
try:
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        address = info[4][0]
        if not address.startswith("127."):
            addresses.add(address)
except OSError:
    pass

# Адрес, через который машина ходит наружу, — обычно тот самый, что виден
# из класса. Пакеты не отправляются: connect на UDP только выбирает маршрут.
try:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.connect(("10.255.255.255", 1))
    addresses.add(probe.getsockname()[0])
    probe.close()
except OSError:
    pass

if not addresses:
    print("    (сетевых адресов не найдено — компьютер не подключён к сети)")
for address in sorted(addresses):
    print(f"    http://{address}:{port}/")
