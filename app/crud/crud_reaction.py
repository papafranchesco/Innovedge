from sqlalchemy.orm import Session
from app.models.models import Reaction, ReactionType

def create_reaction(db: Session, from_user_id: int, to_user_id: int, reaction_type: ReactionType):
    reaction = Reaction(
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        reaction_type=reaction_type
    )
    db.add(reaction)
    db.commit()
    db.refresh(reaction)
    return reaction
