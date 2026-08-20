from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView

app = Flask(__name__)
app.config.from_object(Config)
metadata = MetaData(
  naming_convention={
  "ix": 'ix_%(column_0_label)s',
  "uq": "uq_%(table_name)s_%(column_0_name)s",
  "ck": "ck_%(table_name)s_%(constraint_name)s",
  "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
  "pk": "pk_%(table_name)s"
  }
)

db = SQLAlchemy(app, metadata=metadata)
migrate = Migrate(app, db, render_as_batch=True)

login = LoginManager(app)
login.login_view = 'login'

admin = Admin(app)

from app import routes, models

#########
# ADMIN #
#########

from flask_login import current_user

class AdminModelView(ModelView):

  can_export = True

  def is_accessible(self):
    return True # lol just for now
    #return current_user.username == 'admin'

  def inaccessible_callback(self, name, **kwargs):
    # redirect to login page if user doesn't have access
    return 'Sorry, admin page is not for you.'

class AdminSongModelView(AdminModelView):

  # just to show a demo of using admin panel directly to vet picks
  # in practice, I'll probably export the table to gsheets for the host to vet picks
  column_exclude_list = ['user', ]
  column_editable_list = ['approved', 'approval_message']


from app.models import User, Event, Round, Song, Match, Vote, Candidate
admin.add_view(AdminModelView(User, db.session))
admin.add_view(AdminModelView(Event, db.session))
admin.add_view(AdminModelView(Round, db.session))
admin.add_view(AdminSongModelView(Song, db.session))
admin.add_view(AdminModelView(Match, db.session))
admin.add_view(AdminModelView(Vote, db.session))
admin.add_view(AdminModelView(Candidate, db.session))