import { useQuery } from "@tanstack/react-query";
import { AppointmentService } from "@application/services/AppointmentService";
import { HttpBookingRepository } from "@infrastructure/repositories/HttpBookingRepository";
import apiClient from "@infrastructure/http/client";

const appointmentService = new AppointmentService(new HttpBookingRepository(apiClient));

export const useCalendarAppointments = (date: string) =>
  useQuery({
    queryKey: ["appointments", date],
    queryFn: () => appointmentService.getCalendar(date),
    enabled: Boolean(date),
  });
