"""Map and destination endpoints."""

import os

from fastapi import (APIRouter, Depends, File, Form, HTTPException, UploadFile,
                     status)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_settings
from app.models.destination import Destination
from app.schemas.schemas import (DestinationCreate, DestinationOut,
                                 DestinationUpdate, MapOut)
from app.services import map_service
from app.services.map_service import MapError

router = APIRouter(prefix="/api", tags=["maps"])


@router.get("/maps", response_model=list[MapOut])
def list_maps(db: Session = Depends(get_db)):
    return map_service.list_maps(db)


@router.get("/maps/{map_id}", response_model=MapOut)
def get_map(map_id: int, db: Session = Depends(get_db)):
    record = map_service.get_map(db, map_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    return record


@router.post("/maps", response_model=MapOut, status_code=status.HTTP_201_CREATED)
async def upload_map(name: str = Form(...), description: str | None = Form(None),
                     yaml_file: UploadFile = File(...),
                     image_file: UploadFile = File(...),
                     db: Session = Depends(get_db)):
    """Upload the .yaml and .pgm produced by `rosrun map_server map_saver`."""
    storage = get_settings().map_storage_dir
    os.makedirs(storage, exist_ok=True)

    # Never trust an uploaded filename: a name containing "../" would let an
    # upload write outside the storage directory.
    safe = "".join(c for c in name if c.isalnum() or c in ("-", "_")) or "map"
    yaml_path = os.path.join(storage, "%s.yaml" % safe)
    image_path = os.path.join(storage, "%s.pgm" % safe)

    with open(yaml_path, "wb") as handle:
        handle.write(await yaml_file.read())
    with open(image_path, "wb") as handle:
        handle.write(await image_file.read())

    try:
        return map_service.create_map(db, name, description, yaml_path, image_path)
    except MapError as exc:
        # Do not leave a half-uploaded map on disk after a rejected upload.
        for path in (yaml_path, image_path):
            if os.path.exists(path):
                os.remove(path)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/maps/{map_id}/destinations", response_model=list[DestinationOut])
def list_destinations(map_id: int, db: Session = Depends(get_db)):
    record = map_service.get_map(db, map_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    return record.destinations


@router.get("/destinations", response_model=list[DestinationOut])
def list_all_destinations(db: Session = Depends(get_db)):
    from sqlalchemy import select
    return list(db.scalars(select(Destination).order_by(Destination.name)))


@router.post("/destinations", response_model=DestinationOut,
             status_code=status.HTTP_201_CREATED)
def create_destination(payload: DestinationCreate, db: Session = Depends(get_db)):
    if map_service.get_map(db, payload.map_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "map not found")
    destination = Destination(**payload.model_dump())
    db.add(destination)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "this map already has a destination called %r"
                            % payload.name)
    db.refresh(destination)
    return destination


@router.patch("/destinations/{destination_id}", response_model=DestinationOut)
def update_destination(destination_id: int, payload: DestinationUpdate,
                       db: Session = Depends(get_db)):
    destination = db.get(Destination, destination_id)
    if destination is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "destination not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(destination, field, value)
    db.commit()
    db.refresh(destination)
    return destination


@router.delete("/destinations/{destination_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_destination(destination_id: int, db: Session = Depends(get_db)):
    destination = db.get(Destination, destination_id)
    if destination is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "destination not found")
    db.delete(destination)
    db.commit()
