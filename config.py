import os
basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'ban-lily-fish-staff'
    #SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
    #    'sqlite:///' + os.path.join(basedir, 'data/app.db')
    #SQLALCHEMY_DATABASE_URI = 'sqlite:////home/peyrin/Downloads/showdown/data/app.db'
    SQLALCHEMY_DATABASE_URI = 'sqlite:////data/app.db'