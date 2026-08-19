from dataclasses import dataclass
from datetime import datetime

from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db, login
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

@dataclass
class User(UserMixin, db.Model):
  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  username: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True)
  # thinking of temp hacking this as like ryan@nohomers.net
  email: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True)
  password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))

  songs: so.WriteOnlyMapped['Song'] = so.relationship(back_populates='user')

  def set_password(self, password):
    self.password_hash = generate_password_hash(password)

  def check_password(self, password):
    return check_password_hash(self.password_hash, password)

@login.user_loader
def load_user(id):
  return db.session.get(User, int(id))

@dataclass
class Event(db.Model):
  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  event_slug: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True) # wi27-music
  name: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True) # Winter 2027 Music Showdown

  rounds: so.WriteOnlyMapped['Round'] = so.relationship(back_populates='event')
  songs: so.WriteOnlyMapped['Song'] = so.relationship(back_populates='event')

@dataclass
class Round(db.Model):
  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  event_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Event.id), index=True)
  round_slug: so.Mapped[str] = so.mapped_column(sa.String(256), index=True) # 2a
  start_time: so.Mapped[datetime] = so.mapped_column(sa.DateTime())
  end_time: so.Mapped[datetime] = so.mapped_column(sa.DateTime())

  event: so.Mapped['Event'] = so.relationship(back_populates='rounds')
  matches: so.WriteOnlyMapped['Match'] = so.relationship(back_populates='round')

@dataclass
class Song(db.Model):
  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
  event_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Event.id), index=True)
  artist: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True)
  title: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True)
  link: so.Mapped[str] = so.mapped_column(sa.String(256), index=True, unique=True)

  user: so.Mapped['User'] = so.relationship(back_populates='songs')
  event: so.Mapped['Event'] = so.relationship(back_populates='songs')

@dataclass
class Match(db.Model):
  __tablename__ = 'match'

  id: so.Mapped[int] = so.mapped_column(primary_key=True)
  round_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Round.id), index=True)

  # the match that the winner advances to
  next_match_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey('match.id'), index=True)

  round: so.Mapped['Round'] = so.relationship(back_populates='matches')
  votes: so.WriteOnlyMapped['Vote'] = so.relationship(back_populates='match')
  candidates: so.WriteOnlyMapped['Candidate'] = so.relationship(back_populates='match')

  # one winner from each of the prev_matches shows up in this match
  # the winner of this match advances to next_match
  prev_matches: so.Mapped[list['Match']] = so.relationship('Match', back_populates='next_match', remote_side=[next_match_id])
  next_match: so.Mapped['Match | None'] = so.relationship('Match', back_populates='prev_matches', remote_side=[id])

@dataclass
class Vote(db.Model):
  match_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Match.id), index=True, primary_key=True)
  user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True, primary_key=True)
  song_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Song.id), index=True)
  is_tiebreaker: so.Mapped[bool] = so.mapped_column(default=False)

  sa.UniqueConstraint(match_id, user_id, name='vote once per match')

  match: so.Mapped['Match'] = so.relationship(back_populates='votes')

@dataclass
class Candidate(db.Model):
  song_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Song.id), index=True, primary_key=True)
  match_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(Match.id), index=True, primary_key=True)

  match: so.Mapped['Match'] = so.relationship(back_populates='candidates')
