from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.database import get_db
from app.models import Conversation, Hostel, Message, User
from app.schemas import (
    StartConversationRequest,
    ConversationOut,
    ConversationPreview,
    MessageOut,
    SendMessageRequest,
)
from app.routers.auth import get_current_user  # see note below

router = APIRouter(prefix="/chat", tags=["chat"])


def _get_current_user(db: Session, current_user: dict) -> User:
    user = db.query(User).filter(User.id == current_user["sub"]).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _assert_participant(convo: Conversation, user_id: str) -> None:
    if user_id not in (convo.seeker_id, convo.warden_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this conversation",
        )


@router.post("/conversations", response_model=ConversationOut)
def start_conversation(
    payload: StartConversationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get-or-create a conversation between `me` and `other_user_id`.

    Role rules:
      - seeker starts chat with a warden
      - warden starts chat with a seeker
    Either way we figure out who is who from their roles.
    """
    me = _get_current_user(db, current_user)
    other = db.query(User).filter(User.id == payload.other_user_id).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")
    if other.id == me.id:
        raise HTTPException(status_code=400, detail="Cannot chat with yourself")

    # Normalise seeker/warden slots regardless of who initiated.
    roles = {me.role.value, other.role.value}
    if not ({"seeker", "warden"} <= roles):
        raise HTTPException(
            status_code=400,
            detail="Conversations must be between a seeker and a warden",
        )

    seeker = me if me.role.value == "seeker" else other
    warden = me if me.role.value == "warden" else other

    q = db.query(Conversation).filter(
        Conversation.seeker_id == seeker.id,
        Conversation.warden_id == warden.id,
    )
    if payload.hostel_id:
        q = q.filter(Conversation.hostel_id == payload.hostel_id)
    else:
        q = q.filter(Conversation.hostel_id.is_(None))

    convo = q.first()
    if convo:
        return convo

    convo = Conversation(
        seeker_id=seeker.id,
        warden_id=warden.id,
        hostel_id=payload.hostel_id,
    )
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


@router.get("/conversations", response_model=list[ConversationPreview])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Inbox list for the current user, newest activity first."""
    me = _get_current_user(db, current_user)
    convos = (
        db.query(Conversation)
        .filter(
            or_(
                Conversation.seeker_id == me.id,
                Conversation.warden_id == me.id,
            )
        )
        .order_by(Conversation.last_message_at.desc())
        .all()
    )

    am_seeker = me.role.value == "seeker"
    previews: list[ConversationPreview] = []

    for c in convos:
        # The other participant is whichever slot I'm not in.
        if am_seeker:
            other_id = c.warden_id
        else:
            other_id = c.seeker_id
        other = db.query(User).filter(User.id == other_id).first()

        # Decide what this viewer should see as the "name" of the thread.
        if am_seeker:
            # Seeker talks to a hostel, not a person.
            hostel = (
                db.query(Hostel).filter(Hostel.id == c.hostel_id).first()
                if c.hostel_id
                else None
            )
            display_name = hostel.name if hostel else "Hostel"
            subtitle = "Warden"
        else:
            # Warden talks to a person.
            display_name = other.full_name if other else "Unknown"
            subtitle = "Seeker"

        last_msg = (
            db.query(Message)
            .filter(Message.conversation_id == c.id)
            .order_by(Message.created_at.desc())
            .first()
        )

        unread = (
            db.query(Message)
            .filter(
                Message.conversation_id == c.id,
                Message.sender_id != me.id,
                Message.read_at.is_(None),
            )
            .count()
        )

        previews.append(
            ConversationPreview(
                id=c.id,
                other_user_id=other_id,
                hostel_id=c.hostel_id,
                display_name=display_name,
                subtitle=subtitle,
                last_message_text=last_msg.text if last_msg else None,
                last_message_at=c.last_message_at,
                unread_count=unread,
            )
        )

    return previews


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    me = _get_current_user(db, current_user)
    convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _assert_participant(convo, me.id)

    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == convo.id)
        .order_by(Message.created_at.asc())
        .all()
    )

    # Mark anything from the other person as read now that we're viewing it.
    now = datetime.utcnow()
    touched = False
    for m in msgs:
        if m.sender_id != me.id and m.read_at is None:
            m.read_at = now
            touched = True
    if touched:
        db.commit()
        # refresh so the client sees the new read_at values immediately
        msgs = (
            db.query(Message)
            .filter(Message.conversation_id == convo.id)
            .order_by(Message.created_at.asc())
            .all()
        )
    return msgs


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut)
def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    me = _get_current_user(db, current_user)
    convo = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _assert_participant(convo, me.id)

    msg = Message(
        conversation_id=convo.id,
        sender_id=me.id,
        text=payload.text.strip(),
    )
    db.add(msg)
    convo.last_message_at = msg.created_at or datetime.utcnow()
    db.commit()
    db.refresh(msg)
    return msg