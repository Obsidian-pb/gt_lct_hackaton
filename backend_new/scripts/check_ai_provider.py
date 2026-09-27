"""Проверка настроек ИИ-провайдера и статуса (без печати ключа)."""
import sys

from app.services.ai import get_provider

p = get_provider()
print("provider:", p.provider)
print("model:", p.model)
print("base:", p.base)
if len(sys.argv) > 1 and sys.argv[1] == "status":
    print("status:", p.status())
