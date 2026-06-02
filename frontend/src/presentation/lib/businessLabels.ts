export type BusinessType =
  | "generic"
  | "beauty"
  | "medical"
  | "wellness"
  | "professional_services";

export interface BusinessTypeOption {
  value: BusinessType;
  label: string;
  description: string;
}

export interface BusinessLabels {
  businessType: BusinessType;
  businessNoun: string;
  businessNameLabel: string;
  businessNamePlaceholder: string;
  slugPlaceholder: string;
  publicNotFound: string;
}

export const BUSINESS_TYPE_OPTIONS: BusinessTypeOption[] = [
  { value: "generic", label: "General", description: "Negocios con agenda y atencion profesional." },
  { value: "beauty", label: "Belleza", description: "Barberias, salones, estetica y cuidado personal." },
  { value: "medical", label: "Salud", description: "Consultorios, atencion medica y profesionales de salud." },
  { value: "wellness", label: "Bienestar", description: "Kinesiologia, nutricion, terapias y servicios wellness." },
  { value: "professional_services", label: "Servicios Profesionales", description: "Estudios, asesorias y atencion por cita." },
];

export function getBusinessLabels(input: string | null | undefined): BusinessLabels {
  const businessType = (input ?? "generic") as BusinessType;

  switch (businessType) {
    case "beauty":
      return {
        businessType,
        businessNoun: "salon",
        businessNameLabel: "Nombre del negocio",
        businessNamePlaceholder: "Ej: Estetica Bella",
        slugPlaceholder: "estetica-bella",
        publicNotFound: "Salon no encontrado",
      };
    case "medical":
      return {
        businessType,
        businessNoun: "consultorio",
        businessNameLabel: "Nombre del consultorio",
        businessNamePlaceholder: "Ej: Centro Visual Norte",
        slugPlaceholder: "centro-visual-norte",
        publicNotFound: "Consultorio no encontrado",
      };
    case "wellness":
      return {
        businessType,
        businessNoun: "centro",
        businessNameLabel: "Nombre del centro",
        businessNamePlaceholder: "Ej: Espacio Bienestar",
        slugPlaceholder: "espacio-bienestar",
        publicNotFound: "Centro no encontrado",
      };
    case "professional_services":
      return {
        businessType,
        businessNoun: "estudio",
        businessNameLabel: "Nombre del estudio",
        businessNamePlaceholder: "Ej: Estudio Integral Delta",
        slugPlaceholder: "estudio-integral-delta",
        publicNotFound: "Estudio no encontrado",
      };
    case "generic":
    default:
      return {
        businessType: "generic",
        businessNoun: "negocio",
        businessNameLabel: "Nombre del negocio",
        businessNamePlaceholder: "Ej: Mi Negocio",
        slugPlaceholder: "mi-negocio",
        publicNotFound: "Negocio no encontrado",
      };
  }
}
