import os


#
# DBMS - Система управления базами данных, которая используется в проекте
#
# * На момент последней версии, имеется поддержка только PostgreSQL
#

DBMS = 'PostgreSQL'


#
# Данные для подключения:
#
# DBMS_HOST - IP-адрес
# DBMS_PORT - Порт
# DBMS_USER - Логин
# DBMS_PASSWORD - Пароль
# DBMS_DATABASE - База данных
#

DBMS_HOST = os.getenv('PROJECT_0_POSTGRESQL_HOST')
DBMS_PORT = os.getenv('PROJECT_0_POSTGRESQL_PORT')
DBMS_USER = os.getenv('PROJECT_0_POSTGRESQL_USER')
DBMS_PASSWORD = os.getenv('PROJECT_0_POSTGRESQL_PASSWORD')
DBMS_DATABASE = os.getenv('PROJECT_0_POSTGRESQL_DATABASE')

REDIS_HOST = os.getenv('PROJECT_0_REDIS_HOST')