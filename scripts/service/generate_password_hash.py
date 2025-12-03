#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Утилита для генерации bcrypt хеша пароля администратора.

Использование:
    # Интерактивный режим (ввод пароля вручную)
    python scripts/service/generate_password_hash.py
    
    # Пароль через аргумент (для терминалов без поддержки ввода)
    python scripts/service/generate_password_hash.py "МойНадёжныйПароль123!"

После генерации хеша установите переменную окружения:
    Windows (CMD):
        set ADMIN_PASSWORD_HASH=$2b$12$...ваш_хеш...
    
    Windows (PowerShell):
        $env:ADMIN_PASSWORD_HASH = "$2b$12$...ваш_хеш..."
    
    Linux/Mac:
        export ADMIN_PASSWORD_HASH='$2b$12$...ваш_хеш...'

Также рекомендуется установить случайный JWT_SECRET_KEY:
    Windows (CMD):
        set JWT_SECRET_KEY=ваш_случайный_секрет_минимум_32_символа
    
    Windows (PowerShell):
        $env:JWT_SECRET_KEY = "ваш_случайный_секрет_минимум_32_символа"
    
    Linux/Mac:
        export JWT_SECRET_KEY='ваш_случайный_секрет_минимум_32_символа'

Автор: Alexandr
Дата: 03.12.2025
"""

import getpass
import secrets
import string
import sys

try:
    from passlib.context import CryptContext
except ImportError:
    print("❌ Ошибка: библиотека passlib не установлена!")
    print("   Установите её командой: pip install passlib[bcrypt]")
    exit(1)


def generate_password_hash(password: str) -> str:
    """
    Генерирует bcrypt хеш для пароля.
    
    bcrypt автоматически добавляет соль и использует
    адаптивную функцию хеширования (медленную для защиты от брутфорса).
    
    Args:
        password: Пароль в открытом виде.
        
    Returns:
        str: bcrypt хеш пароля.
    """
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """
    Проверяет пароль против хеша (для тестирования).
    
    Args:
        password: Пароль в открытом виде.
        hashed: bcrypt хеш.
        
    Returns:
        bool: True если пароль верный.
    """
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.verify(password, hashed)


def generate_secret_key(length: int = 32) -> str:
    """
    Генерирует криптографически безопасный секретный ключ.
    
    Args:
        length: Длина ключа (по умолчанию 32 символа).
        
    Returns:
        str: Случайный секретный ключ.
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def safe_input_password(prompt: str) -> str:
    """
    Безопасный ввод пароля с fallback на обычный input.
    
    Некоторые терминалы (например, в IDE) не поддерживают getpass.
    В таком случае используется обычный input с предупреждением.
    
    Args:
        prompt: Приглашение для ввода.
        
    Returns:
        str: Введённый пароль.
    """
    try:
        # Пробуем скрытый ввод
        return getpass.getpass(prompt)
    except (KeyboardInterrupt, EOFError):
        raise  # Пробрасываем Ctrl+C
    except Exception:
        # Fallback на обычный ввод
        print("⚠️  Скрытый ввод недоступен. Пароль будет виден при вводе!")
        return input(prompt)


def main():
    """
    Главная функция утилиты.
    
    Использование:
        python generate_password_hash.py                  # Интерактивный ввод
        python generate_password_hash.py "МойПароль123"   # Пароль через аргумент
    """
    print("=" * 60)
    print("🔐 ГЕНЕРАТОР ХЕША ПАРОЛЯ ДЛЯ АДМИН-ПАНЕЛИ")
    print("=" * 60)
    print()
    
    # Проверяем аргумент командной строки
    if len(sys.argv) > 1:
        # Пароль передан как аргумент
        password = sys.argv[1]
        print(f"📥 Пароль получен из аргумента командной строки")
        print(f"   Длина пароля: {len(password)} символов")
        print()
    else:
        # Интерактивный ввод
        print("Введите пароль для админ-панели:")
        print("💡 Совет: можно передать пароль как аргумент:")
        print('   python generate_password_hash.py "ВашПароль"')
        print()
        
        try:
            password = safe_input_password("Пароль: ")
        except KeyboardInterrupt:
            print("\n❌ Отменено пользователем")
            return
        
        if not password:
            print("❌ Пароль не может быть пустым!")
            return
        
        # Подтверждение пароля (только при интерактивном вводе)
        try:
            password_confirm = safe_input_password("Подтвердите пароль: ")
        except KeyboardInterrupt:
            print("\n❌ Отменено пользователем")
            return
        
        if password != password_confirm:
            print("❌ Пароли не совпадают!")
            return
    
    # Проверка сложности пароля
    if len(password) < 8:
        print("⚠️  Внимание: пароль слишком короткий (менее 8 символов)!")
        print("   Рекомендуется использовать более длинный пароль.")
        print()
    
    # Генерация хеша
    print()
    print("⏳ Генерация bcrypt хеша...")
    password_hash = generate_password_hash(password)
    
    # Проверка хеша
    if not verify_password(password, password_hash):
        print("❌ Ошибка верификации хеша!")
        return
    
    print("✅ Хеш успешно сгенерирован и проверен!")
    print()
    
    # Генерация JWT секрета
    jwt_secret = generate_secret_key(32)
    
    # Вывод результатов
    print("=" * 60)
    print("📋 РЕЗУЛЬТАТЫ")
    print("=" * 60)
    print()
    print("1️⃣  ХЕШ ПАРОЛЯ (ADMIN_PASSWORD_HASH):")
    print(f"    {password_hash}")
    print()
    print("2️⃣  СЛУЧАЙНЫЙ JWT СЕКРЕТ (JWT_SECRET_KEY):")
    print(f"    {jwt_secret}")
    print()
    print("=" * 60)
    print("📝 ИНСТРУКЦИЯ ПО УСТАНОВКЕ")
    print("=" * 60)
    print()
    print("Windows (PowerShell):")
    print(f'    $env:ADMIN_PASSWORD_HASH = "{password_hash}"')
    print(f'    $env:JWT_SECRET_KEY = "{jwt_secret}"')
    print()
    print("Windows (CMD):")
    print(f'    set ADMIN_PASSWORD_HASH={password_hash}')
    print(f'    set JWT_SECRET_KEY={jwt_secret}')
    print()
    print("Linux/Mac (bash):")
    print(f"    export ADMIN_PASSWORD_HASH='{password_hash}'")
    print(f"    export JWT_SECRET_KEY='{jwt_secret}'")
    print()
    print("=" * 60)
    print("⚠️  ВАЖНО:")
    print("   - Никогда не храните пароль в открытом виде!")
    print("   - Сохраните хеш и секрет в безопасном месте")
    print("   - Не добавляйте эти значения в git репозиторий")
    print("   - Для продакшена используйте .env файл или secrets manager")
    print("=" * 60)


if __name__ == "__main__":
    main()

