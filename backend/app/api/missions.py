"""Mission endpoints - the ones the Deploy button uses."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_ros
from app.models.mission import MissionStatus
from app.ros.ros_client import RosClient
from app.schemas.schemas import MissionCreate, MissionDetailOut, MissionOut
from app.services import mission_service
from app.services.mission_service import MissionError

router = APIRouter(prefix="/api/missions", tags=["missions"])


@router.get("", response_model=list[MissionOut])
def list_missions(robot_id: int | None = None,
                  mission_status: MissionStatus | None = Query(default=None,
                                                               alias="status"),
                  limit: int = Query(default=100, ge=1, le=1000),
                  db: Session = Depends(get_db)):
    return mission_service.list_missions(db, robot_id=robot_id,
                                         status=mission_status, limit=limit)


@router.post("", response_model=MissionOut, status_code=status.HTTP_201_CREATED)
def create_mission(payload: MissionCreate, db: Session = Depends(get_db),
                   ros: RosClient = Depends(get_ros)):
    try:
        return mission_service.create_mission(
            db, ros, robot_id=payload.robot_id,
            destination_id=payload.destination_id,
            goal_x=payload.goal_x, goal_y=payload.goal_y,
            goal_yaw=payload.goal_yaw, preempt=payload.preempt)
    except MissionError as exc:
        # 409 for "the fleet is not in a state where this is possible",
        # which is what the website needs to distinguish from a bad request.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("/{mission_id}", response_model=MissionDetailOut)
def get_mission(mission_id: int, db: Session = Depends(get_db)):
    mission = mission_service.get_mission(db, mission_id)
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    return mission


@router.post("/{mission_id}/cancel", response_model=MissionOut)
def cancel_mission(mission_id: int, reason: str = "cancelled from the dashboard",
                   db: Session = Depends(get_db),
                   ros: RosClient = Depends(get_ros)):
    mission = mission_service.get_mission(db, mission_id)
    if mission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mission not found")
    try:
        return mission_service.cancel_mission(db, ros, mission, reason)
    except MissionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
