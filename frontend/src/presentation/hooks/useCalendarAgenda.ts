import { useQuery } from "@tanstack/react-query";

import apiClient from "@infrastructure/http/client";

export interface CalendarAgendaAppointment {
  public_id: string;
  starts_at: string;
  ends_at: string;
  status: string;
  notes?: string | null;
  service_name: string;
  service_id: string;
  staff_name: string;
  staff_id: string;
  client_name: string;
  client_id: string;
}

export const useCalendarAgenda = (fromDate: string, toDate: string) =>
  useQuery<CalendarAgendaAppointment[]>({
    queryKey: ["calendar-agenda", fromDate, toDate],
    enabled: Boolean(fromDate && toDate),
    queryFn: async () => {
      const { data } = await apiClient.get<{ results: CalendarAgendaAppointment[] }>("/appointments/search", {
        params: {
          from_date: fromDate,
          to_date: toDate,
          page: 1,
          page_size: 500,
        },
      });
      return data.results || [];
    },
  });
