import os
import sys
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy import create_engine

Base = declarative_base()

class Team(Base):
    __tablename__ = 'team'

    id = Column(Integer, primary_key=True)
    name = Column(String(250), nullable=False)

    @property
    def serialize(self):
        """Return object data in easily serializeable format"""
        return{
            'name': self.name,
            'city': self.city,
            'state': self.state,
            'id': self.id,
        }


class Player(Base):
    __tablename__ = 'player'

    name = Column(String(250), nullable=False)
    id = Column(Integer, primary_key=True)
    position = Column(String(20))
    team_id = Column(Integer, ForeignKey('team.id'))
    team = relationship(Team)

    @property
    def serialize(self):
        """Return object data in easily serializable format"""
        return{
            'name': self.name,
            'position': self.position,
            'role': self.role,
            'id': self.id,
        }


engine = create_engine('sqlite:///basketballteam.db')

Base.metadata.create_all(engine)