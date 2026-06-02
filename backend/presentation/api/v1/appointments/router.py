from fastapi import APIRouter, Depends, HTTPException, status
from datetime import date
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from application.dtos.appointment_dtos import CreateAppointmentRequest, AppointmentResponse
from application.services.appointment_service import AppointmentService
from infrastructure.persistence.repositories.appointment_repository import AppointmentRepository
from infrastructure.persistence.repositories.staff_repository import StaffRepository
from domain.exceptions.base_exceptions import ConflictError, EntityNotFoundError

router = APIRouter(prefix="/appointments", tags=["Appointments"])

async def get_appointment_service(db: AsyncSession = Depends(get_db)) -> AppointmentService:
    repository = AppointmentRepository(db)
    staff_repository = StaffRepository(db)
    return AppointmentService(repository, staff_repository)

@router.get("", response_model=List[AppointmentResponse])
async def list_appointments(
    date_val: date,
    service: AppointmentService = Depends(get_appointment_service)
):
    # En un escenario real, el store_id vendría del contexto multi-tenant
    # Por ahora usamos un placeholder
    STORE_ID = "store-1"
    return await service.list_by_date(STORE_ID, date_val)

@router.post("", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    request: CreateAppointmentRequest,
    service: AppointmentService = Depends(get_appointment_service)
):
    STORE_ID = "store-1"
    try:
        return await service.create(request, STORE_ID)
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    appointment_id: str,
    service: AppointmentService = Depends(get_appointment_service)
):
    try:
        return await service.get_by_id(appointment_id)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.post("/{appointment_id}/confirm", response_model=AppointmentResponse)
async def confirm_appointment(
    appointment_id: str,
    service: AppointmentService = Depends(get_appointment_service)
):
    try:
        return await service.confirm(appointment_id)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
