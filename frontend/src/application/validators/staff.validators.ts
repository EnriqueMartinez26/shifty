import { z } from "zod";

export const createStaffSchema = z.object({
  first_name: z.string().min(2, "Nombre muy corto"),
  last_name: z.string().min(2, "Apellido muy corto"),
  email: z.string().email("Email inválido"),
  display_name: z.string().min(2, "Nombre de muestra muy corto"),
  service_ids: z.array(z.string()).min(1, "Debe tener al menos un servicio asignado"),
});

export type CreateStaffSchema = z.infer<typeof createStaffSchema>;
