from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_admin import Admin

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
from flask_admin.form import TimeField
from flask_admin.contrib.sqla import ModelView

class AdminModelView(ModelView):

  can_export = True

  def is_accessible(self):
    #return True # lol just for now
    return current_user.is_authenticated and current_user.username == 'peyrin'

  def inaccessible_callback(self, name, **kwargs):
    # redirect to login page if user doesn't have access
    return 'Sorry, this admin page is not for you.'

class HostModelView(ModelView):
  can_export = False

  def is_accessible(self):
    #return True # lol just for now
    return current_user.is_authenticated and current_user.username == 'oboopa staloopa' # replace with username of host

  def inaccessible_callback(self, name, **kwargs):
    # redirect to login page if user doesn't have access
    return 'Sorry, this admin page is not for you.'

class AdminUserModelView(AdminModelView):
  column_exclude_list = ['password_hash', ]
  column_editable_list = ['is_verified']

class AdminSongModelView(AdminModelView):
  column_editable_list = ['approved', 'approval_message']

class HostSongModelView(HostModelView):
  column_exclude_list = ['user', ]
  column_editable_list = ['approved', 'approval_message']
  can_delete = False
  form_edit_rules = ('event', 'artist', 'title', 'link', 'pick_time', 'pick_num', 'approved', 'approval_message')
  form_widget_args = {
    'event': {'disabled': True},
    'artist': {'disabled': True},
    'title': {'disabled': True},
    'link': {'disabled': True},
    'pick_time': {'disabled': True},
    'pick_num': {'disabled': True},
  }

class AdminEventModelView(AdminModelView):
  column_editable_list = ['pick_deadline']
  form_overrides = {
    'Pick Deadline': TimeField
  }
  form_args = {
    'Pick Deadline': {
      'format': '%Y-%m-%d %H:%M:%S'
    }
  }


from app.models import User, Event, Round, Song, Match, Vote, Candidate
admin.add_view(AdminUserModelView(User, db.session))
admin.add_view(AdminEventModelView(Event, db.session))
admin.add_view(AdminModelView(Round, db.session))
admin.add_view(AdminSongModelView(Song, db.session))
admin.add_view(HostSongModelView(Song, db.session, name='Approve Picks', endpoint='approve-picks'))
admin.add_view(AdminModelView(Match, db.session))
admin.add_view(AdminModelView(Vote, db.session))
admin.add_view(AdminModelView(Candidate, db.session))