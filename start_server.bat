@echo off
cd /d "C:\Users\Azizbek\PyCharmProjects\medhelper"
call .venv\Scripts\activate.bat
python manage.py runserver
pause
