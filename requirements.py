import subprocess

def install_requirements():
    # Устанавливаем библиотеки из файла requirements.txt
    subprocess.check_call(["pip", "install", "-r", "requirements.txt"])


# Запуск установки
if __name__ == '__main__':
    install_requirements()
