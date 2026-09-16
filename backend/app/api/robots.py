"""Robot endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_settings
from app.models.robot import RobotMode
from app.schemas.schemas import RobotCreate, RobotOut, RobotUpdate
from app.services import robot_service

router = APIRouter(prefix="/api/robots", tags=["robots"])


@router.get("", response_model=list[RobotOut])
def list_robots(db: Session = Depends(get_db)):
    # Recompute staleness on read: a robot that stopped reporting must show
    # as OFFLINE even if nothing has pushed an update since.
    robot_service.refresh_statuses(db, get_settings().robot_offline_after_seconds)
    return robot_service.list_robots(db)


@router.post("", response_model=RobotOut, status_code=status.HTTP_201_CREATED)
def create_robot(payload: RobotCreate, db: Session = Depends(get_db)):
    if payload.camera_url and payload.mode is RobotMode.SIMULATED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a SIMULATED robot cannot have a camera; the camera is a property "
            "of real hardware")
    try:
        robot = robot_service.create_robot(db, payload.code, payload.name,
                                           payload.mode)
        if payload.camera_url:
            robot.camera_url = payload.camera_url
            db.commit()
            db.refresh(robot)
        return robot
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "a robot with code %r already exists" % payload.code)


@router.get("/{robot_id}", response_model=RobotOut)
def get_robot(robot_id: int, db: Session = Depends(get_db)):
    robot = robot_service.get_robot(db, robot_id)
    if robot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "robot not found")
    return robot


@router.patch("/{robot_id}", response_model=RobotOut)
def update_robot(robot_id: int, payload: RobotUpdate, db: Session = Depends(get_db)):
    robot = robot_service.get_robot(db, robot_id)
    if robot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "robot not found")
    if payload.name is not None:
        robot.name = payload.name
    if payload.mode is not None:
        robot.mode = payload.mode
        # Switching a robot back to SIMULATED drops its camera with it,
        # rather than leaving an address that can no longer be reached.
        if robot.mode is RobotMode.SIMULATED:
            robot.camera_url = None
    if payload.camera_url is not None:
        # An explicit empty string means "this robot no longer has a camera".
        wanted = payload.camera_url or None
        if wanted and robot.mode is RobotMode.SIMULATED:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "robot %s is SIMULATED; set mode to REAL before giving it a "
                "camera" % robot.code)
        robot.camera_url = wanted
    db.commit()
    db.refresh(robot)
    return robot


@router.delete("/{robot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_robot(robot_id: int, db: Session = Depends(get_db)):
    robot = robot_service.get_robot(db, robot_id)
    if robot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "robot not found")
    robot_service.delete_robot(db, robot)
