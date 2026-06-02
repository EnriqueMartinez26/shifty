import pytest
from datetime import datetime, timedelta
from domain.value_objects.time_slot import TimeSlot
from domain.entities.appointment import Appointment, AppointmentStatus

def test_time_slot_overlaps():
    start = datetime(2026, 1, 1, 10, 0)
    ts1 = TimeSlot.from_start_and_duration(start, 30)
    
    # Overlapping slot
    ts2 = TimeSlot.from_start_and_duration(start + timedelta(minutes=15), 30)
    assert ts1.overlaps_with(ts2) is True
    
    # Non-overlapping slot (after)
    ts3 = TimeSlot.from_start_and_duration(start + timedelta(minutes=30), 30)
    assert ts1.overlaps_with(ts3) is False
    
    # Non-overlapping slot (before)
    ts4 = TimeSlot.from_start_and_duration(start - timedelta(minutes=30), 30)
    assert ts1.overlaps_with(ts4) is False

def test_appointment_transitions():
    ts = TimeSlot.from_start_and_duration(datetime.now(), 30)
    apt = Appointment(
        id="1", service_id="s1", staff_id="st1", store_id="st1",
        time_slot=ts, client_name="Test"
    )
    
    assert apt.status == AppointmentStatus.PENDING
    
    apt.confirm()
    assert apt.status == AppointmentStatus.CONFIRMED
    
    apt.complete()
    assert apt.status == AppointmentStatus.COMPLETED

def test_appointment_invalid_transition():
    ts = TimeSlot.from_start_and_duration(datetime.now(), 30)
    apt = Appointment(
        id="1", service_id="s1", staff_id="st1", store_id="st1",
        time_slot=ts, client_name="Test"
    )
    
    with pytest.raises(ValueError, match="Can only complete confirmed appointments"):
        apt.complete()
