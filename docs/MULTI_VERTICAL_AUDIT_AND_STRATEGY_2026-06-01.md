# Shifty Multi-Rubro: Auditoria y Estrategia

## Objetivo

Convertir Shifty de "turnero para salones/barberias" a "turnero SaaS para servicios profesionales", sin descartar el vertical de estetica y sin reescribir el core actual.

La estrategia correcta no es cambiar toda la nomenclatura interna de golpe. La estrategia correcta es:

1. conservar el core de agenda multi-tenant ya implementado
2. desacoplar el producto del rubro belleza en UI, copy y configuracion
3. agregar configuracion por vertical para que el mismo motor sirva para:
   - barberias y salones
   - consultorios
   - bienestar
   - estudios profesionales
   - servicios con agenda por profesional

## Diagnostico

El proyecto ya tiene un nucleo bastante transversal:

- tenant por negocio
- usuarios con roles
- profesionales
- servicios
- horarios
- disponibilidad
- bloqueos
- turnos
- OTP
- pagos
- ledger
- reportes
- portal publico

Eso ya es un "motor de turnos". El problema actual no esta en la base de agenda, sino en estas dos capas:

- producto y copy: todavia habla como si el sistema fuera solo para salones
- configuracion y modelo: faltan campos y presets para rubros no esteticos

## Lo que ya esta bien para un producto multi-rubro

### Core backend reutilizable

- `stores`, `staff`, `services`, `appointments`, `appointment_blocks`, `payments`, `ledger`
- disponibilidad basada en horarios, turnos, bloqueos y reglas de anticipo
- auth multi-tenant y roles canonicos
- portal publico con OTP opcional

### Core frontend reutilizable

- dashboard por negocio
- settings de marca y politicas
- calendario interno
- booking publico
- pagos
- ledger
- reportes

## Auditoria: que hoy ata el producto a barberias/salones

### 1. Acoplamiento fuerte en copy/UI

Estos archivos usan lenguaje especifico de salon:

- `frontend/src/presentation/pages/Settings.tsx`
- `frontend/src/presentation/pages/Register.tsx`
- `frontend/src/presentation/pages/Login.tsx`
- `frontend/src/presentation/pages/Dashboard.tsx`
- `frontend/src/presentation/layouts/AdminLayout.tsx`
- `frontend/src/presentation/pages/PublicBooking.tsx`

Patrones encontrados:

- "Nombre del Salon"
- "Registra tu Salon"
- "Gestiona tu salon"
- "Impulsa tu Salon"
- "Salon no encontrado"
- ejemplos como "Estetica Bella" o "Salon Estilo Pro"

Impacto:

- no rompe funcionalidad
- si rompe posicionamiento comercial y percepcion de producto
- un oculista, psicologo o abogado siente que el sistema "no es para el"

### 2. Acoplamiento en mensajes backend y validaciones

Archivos afectados:

- `backend/modules/public/router.py`
- `backend/modules/auth/router.py`
- `frontend/src/application/validators/booking.validators.ts`

Patrones:

- errores como "Salon no encontrado"
- alta publica pensada como "registrar salon"
- booking validator con mensaje "ID de salon requerido"

Impacto:

- menor a nivel tecnico
- alto a nivel coherencia de producto/API

### 3. Acoplamiento en onboarding y branding

El onboarding actual crea una "tienda/salon" y solo contempla:

- nombre
- slug
- admin

No contempla:

- tipo de negocio
- vertical
- nombre visible del cliente final
- reglas por rubro
- formulario publico configurable

Impacto:

- para belleza funciona
- para verticales distintos obliga a adaptar todo a mano despues

### 4. Seed, tests y documentacion sesgados a belleza

Archivos afectados:

- `backend/scripts/seed_simulation.py`
- `backend/scripts/check_db.py`
- `backend/tests/integration/test_appointments_api.py`
- `docs/DOCUMENTACION_TURNERO.md`
- `docs/PROJECT_CONTEXT.md`
- `docs/ANALISIS_3NF.md`
- `docs/DB_DESIGN_3NF_RLS_AUDIT.md`

Patrones:

- stores de ejemplo "Barberia Sentinel" y "Salon Sentinel"
- servicios como "Corte", "Barba", "Brushing"
- documentacion que define el producto como sistema para salones/barberias

Impacto:

- no afecta el runtime
- si afecta demos, QA, ventas, discurso comercial y percepcion del alcance real

### 5. Gaps reales del modelo para soportar consultorios y otros rubros

#### Falta `business_type` o `vertical`

Hoy `Store` no expresa a que rubro pertenece el negocio.

Consecuencia:

- no se puede adaptar la UI segun rubro
- no se pueden cargar presets de formularios, mensajes y reglas

#### Faltan campos configurables del cliente/paciente

El booking publico actual captura:

- `client_name`
- `client_phone`
- `client_email`
- `notes`

Para un oculista o consultorio esto es corto. Suele hacer falta:

- dni/documento
- fecha de nacimiento
- motivo de consulta
- primera vez / control
- cobertura / obra social
- consentimiento o notas previas

#### Falta formulario publico configurable por vertical

Hoy el flujo publico asume una reserva simple.

Falta:

- preguntas previas opcionales
- campos requeridos segun rubro
- textos de consentimiento
- instrucciones previas/posteriores

#### Falta capacidad de recursos compartidos

Hoy el motor agenda principalmente por profesional.

Para algunos rubros puede hacer falta:

- consultorio
- gabinete
- equipo
- sala

No es imprescindible para la primera apertura multi-rubro, pero si para escalar a clinicas chicas o centros mas complejos.

#### Falta lenguaje neutral en el dominio expuesto

Internamente `Store` puede mantenerse por ahora. El problema es exponer eso como "salon" en UI y API.

## Estrategia de rediseño correcta

## Principio 1: no renombrar todo el dominio interno de golpe

No recomiendo empezar con un refactor masivo de:

- `Store -> Business`
- `Staff -> Provider`
- `Client -> Patient`

Eso es caro y arriesga romper demasiado.

Recomendacion:

- mantener internamente `Store`, `Staff`, `Service`, `Appointment`
- agregar una capa de presentacion/configuracion que cambie etiquetas y comportamiento por vertical

## Principio 2: introducir verticales/presets

Agregar al negocio:

- `business_type` o `vertical`

Valores sugeridos:

- `beauty`
- `medical`
- `wellness`
- `professional_services`
- `generic`

Este campo debe gobernar:

- copy del frontend
- placeholders
- campos requeridos del booking publico
- plantillas de notificacion
- widgets sugeridos del dashboard
- textos de onboarding

## Principio 3: hacer configurable el intake publico

Agregar una configuracion por tienda:

- `public_booking_form`
- `custom_client_fields`
- `consent_text`
- `intake_questions`

Estructura sugerida:

- lista de campos
- label
- tipo (`text`, `textarea`, `select`, `boolean`, `date`)
- requerido
- visible en verticales/publico/backoffice

## Principio 4: agregar metadatos por servicio

Extender `Service` para soportar tipos de atencion distintos.

Campos sugeridos:

- `category`
- `buffer_before_minutes`
- `buffer_after_minutes`
- `requires_intake`
- `intake_template_key`
- `delivery_mode` (`in_person`, `virtual`, `hybrid`)

Esto permite, por ejemplo:

- consulta inicial de oftalmologia: 40 min, buffer 10 min, intake obligatorio
- control simple: 20 min, sin intake extendido

## Principio 5: extender el perfil del cliente sin convertirlo en historia clinica

Para no meterse de lleno en compliance medico al principio:

- mantener `User`/cliente como perfil liviano
- agregar `profile_metadata` o `custom_fields`

Campos sugeridos:

- `date_of_birth`
- `document_number`
- `insurance_provider`
- `insurance_member_id`
- `tags`
- `custom_fields`

Advertencia:

- si se apunta a salud, no conviene venderlo inicialmente como sistema clinico o historia medica
- conviene venderlo como agenda y gestion de turnos para consultorios

## Principio 6: texto comercial y UX neutrales por defecto

El default de producto debe pasar a ser:

- "negocio"
- "empresa"
- "centro"
- "profesional"
- "cliente"
- "reserva"
- "servicio"

Y si `business_type = medical`, la UI puede mutar ciertas etiquetas a:

- cliente -> paciente
- servicio -> consulta
- reserva -> turno

## Propuesta de arquitectura de producto

## Capa 1. Core transversal

Mantener:

- auth
- tenancy
- roles
- staff
- services
- appointments
- blocks
- payments
- ledger
- reports
- public booking

## Capa 2. Configuracion por vertical

Agregar:

- `business_type`
- `vertical_config`
- `custom_labels`
- `public_booking_form`
- `notification_templates`

## Capa 3. Extensiones opcionales

Fase posterior:

- recursos/rooms
- sucursales
- multisitio
- teleconsulta
- consentimientos
- integraciones sectoriales

## Funciones que deberia tener el producto transversal

### Base para cualquier rubro

- agenda por profesional
- horarios y bloqueos
- servicios configurables
- reserva publica
- confirmacion/cancelacion/reprogramacion
- OTP opcional
- pagos y senas
- ledger de deuda
- reportes
- branding

### Extras para consultorios/profesionales

- motivo de consulta
- primera vez / control
- buffers por servicio
- instrucciones previas
- campos adicionales del cliente
- recordatorios mas formales

### Extras para estetica

- servicios visuales
- redes/WhatsApp mas visibles
- promociones
- enfoque fuerte en marca

## Roadmap recomendado para pasar a multi-rubro

## Fase 1. Desacople comercial y visual

Cambios:

- reemplazar lenguaje "salon" por lenguaje neutral en frontend
- reemplazar mensajes de API expuestos al usuario
- actualizar onboarding y placeholders
- reescribir docs de producto para "servicios profesionales"

Resultado:

- el producto ya no se presenta como solo belleza

## Fase 2. Configuracion por vertical

Cambios:

- agregar `business_type` a `Store`
- exponerlo en registro, settings y API
- cargar presets por vertical

Resultado:

- un negocio nuevo puede declararse como salon, consultorio, estudio o generico

## Fase 3. Formulario publico configurable

Cambios:

- intake fields configurables
- campos extras en reserva publica
- render dinamico de formulario

Resultado:

- el mismo booking sirve tanto para "corte de cabello" como para "consulta de control"

## Fase 4. Perfil extendido de cliente

Cambios:

- metadata configurable de cliente
- vista de ficha mas flexible
- filtros/reportes por campos clave

Resultado:

- mejor soporte para consultorios y profesionales

## Fase 5. Recursos y complejidad opcional

Cambios:

- rooms/resources
- disponibilidad compuesta
- restricciones avanzadas

Resultado:

- apertura a clinicas chicas, centros esteticos complejos y otros escenarios

## Backlog tecnico concreto

### Alta prioridad

1. agregar `business_type` a backend/frontend
2. neutralizar copy de frontend y mensajes de API
3. ajustar registro/settings para negocio transversal
4. agregar `custom_fields` / `public_booking_form`
5. soportar campos extra en reserva publica

### Media prioridad

1. presets por vertical
2. notificaciones distintas por vertical
3. seed multi-rubro
4. documentacion comercial neutra

### Prioridad posterior

1. recursos/rooms
2. sucursales
3. compliance sectorial especifico

## Conclusiones

- Shifty ya tiene base tecnica para ser un turnero multi-rubro.
- Hoy esta presentado y parcialmente configurado como producto para salones/barberias.
- El mayor trabajo no es reescribir el motor de agenda.
- El mayor trabajo es desacoplar copy, onboarding y configuracion del rubro belleza.
- Para que un oculista lo use bien, lo minimo necesario es:
  - `business_type`
  - labels neutros o por vertical
  - intake configurable
  - perfil de cliente ampliable
  - opciones de servicio mas expresivas
