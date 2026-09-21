import { useEffect, useState, type FormEvent } from "react";

import { PublicAppointmentLookup } from "./PublicAppointmentLookup";

type Branch = "chiconcuac" | "texcoco";

type PublicService = {
  name: string;
  duration_minutes: number;
  price: string;
};

type ServiceState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; services: PublicService[] }
  | { kind: "error" };

type AvailabilityState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; starts: string[] }
  | { kind: "error" };

type CustomerForm = {
  firstName: string;
  lastName: string;
  phone: string;
  email: string;
  privacyNoticeAccepted: boolean;
  contactProcessingAuthorized: boolean;
  adultResponsibilityDeclared: boolean;
};

type CustomerErrors = Partial<Record<keyof CustomerForm, string>>;

type PrivacyNoticeState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; notice: PublicPrivacyNotice }
  | { kind: "error" };

type PublicPrivacyNotice = { version: string; content: string };

type ConfirmationResult = {
  privateCode: string;
  appointment: {
    serviceName: string;
    branch: string;
    scheduledStart: string;
    durationMinutes: number;
    price: string;
    status: string;
  };
  notifications: Array<{ channel: string; status: string }>;
};

type SubmissionState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "error"; message: string; alternatives: string[]; requiresDifferentDate: boolean }
  | { kind: "success"; result: ConfirmationResult };

type BookingStep = "appointment" | "details" | "confirm" | "success";
type PublicView = "booking" | "lookup";

const emptyCustomerForm: CustomerForm = {
  firstName: "",
  lastName: "",
  phone: "",
  email: "",
  privacyNoticeAccepted: false,
  contactProcessingAuthorized: false,
  adultResponsibilityDeclared: false,
};

const branches: Array<{ id: Branch; name: string; image?: string }> = [
  { id: "texcoco", name: "Texcoco", image: "/assets/brand/sucursal1.png" },
  { id: "chiconcuac", name: "Chiconcuac", image: "/assets/brand/sucursal2.png" },
];

export function PublicApp() {
  const [publicView, setPublicView] = useState<PublicView>("booking");
  const [branch, setBranch] = useState<Branch | null>(null);
  const [selectedService, setSelectedService] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedStart, setSelectedStart] = useState<string | null>(null);
  const [serviceState, setServiceState] = useState<ServiceState>({ kind: "idle" });
  const [availabilityState, setAvailabilityState] = useState<AvailabilityState>({ kind: "idle" });
  const [requestVersion, setRequestVersion] = useState(0);
  const [availabilityRequestVersion, setAvailabilityRequestVersion] = useState(0);
  const [customerForm, setCustomerForm] = useState<CustomerForm>(emptyCustomerForm);
  const [customerErrors, setCustomerErrors] = useState<CustomerErrors>({});
  const [customerFormStatus, setCustomerFormStatus] = useState<string | null>(null);
  const [bookingStep, setBookingStep] = useState<BookingStep>("appointment");
  const [privacyNoticeState, setPrivacyNoticeState] = useState<PrivacyNoticeState>({ kind: "idle" });
  const [confirmationReference, setConfirmationReference] = useState<string | null>(null);
  const [submissionState, setSubmissionState] = useState<SubmissionState>({ kind: "idle" });

  useEffect(() => {
    if (branch === null) {
      setServiceState({ kind: "idle" });
      return;
    }

    const controller = new AbortController();
    setServiceState({ kind: "loading" });

    void loadServices(branch, controller.signal)
      .then((services) => setServiceState({ kind: "ready", services }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setServiceState({ kind: "error" });
      });

    return () => controller.abort();
  }, [branch, requestVersion]);

  useEffect(() => {
    setSelectedStart(null);
    if (branch === null || selectedService === null || selectedDate === "") {
      setAvailabilityState({ kind: "idle" });
      return;
    }

    const controller = new AbortController();
    setAvailabilityState({ kind: "loading" });
    void loadAvailability(branch, selectedService, selectedDate, controller.signal)
      .then((starts) => setAvailabilityState({ kind: "ready", starts }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setAvailabilityState({ kind: "error" });
      });
    return () => controller.abort();
  }, [branch, selectedService, selectedDate, availabilityRequestVersion]);

  useEffect(() => {
    if (bookingStep !== "confirm" || privacyNoticeState.kind !== "idle") return;
    const controller = new AbortController();
    setPrivacyNoticeState({ kind: "loading" });
    void loadPrivacyNotice(controller.signal)
      .then((notice) => setPrivacyNoticeState({ kind: "ready", notice }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setPrivacyNoticeState({ kind: "error" });
      });
    return () => controller.abort();
  }, [bookingStep]);

  function selectBranch(nextBranch: Branch) {
    setBranch(nextBranch);
    setSelectedService(null);
    setSelectedDate("");
    setSelectedStart(null);
    setCustomerErrors({});
    setCustomerFormStatus(null);
    setBookingStep("appointment");
    resetConfirmation();
  }

  function updateCustomerField<K extends keyof CustomerForm>(field: K, value: CustomerForm[K]) {
    setCustomerForm((current) => ({ ...current, [field]: value }));
    setCustomerErrors((current) => ({ ...current, [field]: undefined }));
    setCustomerFormStatus(null);
    resetConfirmation();
  }

  function validateCustomerForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validateCustomerData(customerForm);
    setCustomerErrors(errors);
    if (Object.keys(errors).length === 0) {
      setCustomerFormStatus(null);
      setBookingStep("confirm");
    } else {
      setCustomerFormStatus(null);
    }
  }

  function resetConfirmation() {
    setPrivacyNoticeState({ kind: "idle" });
    setConfirmationReference(null);
    setSubmissionState({ kind: "idle" });
  }

  async function confirmAppointment() {
    if (
      branch === null || selectedService === null || selectedStart === null ||
      privacyNoticeState.kind !== "ready"
    ) return;
    setSubmissionState({ kind: "submitting" });
    try {
      const reference = confirmationReference ?? await issueConfirmationReference();
      setConfirmationReference(reference);
      const response = await fetch("/api/public/appointments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          confirmationReference: reference,
          firstName: customerForm.firstName,
          lastName: customerForm.lastName,
          phone: customerForm.phone,
          email: customerForm.email,
          serviceName: selectedService,
          branch,
          scheduledStart: selectedStart,
          privacyConsent: {
            noticeVersion: privacyNoticeState.notice.version,
            privacyNoticeAccepted: customerForm.privacyNoticeAccepted,
            contactProcessingAuthorized: customerForm.contactProcessingAuthorized,
            adultResponsibilityDeclared: customerForm.adultResponsibilityDeclared,
          },
        }),
      });
      if (response.status === 409) {
        const conflict = await readConflict(response);
        setSubmissionState({ kind: "error", ...conflict });
        return;
      }
      if (response.status === 404) setConfirmationReference(null);
      if (!response.ok) {
        setSubmissionState({ kind: "error", message: "No fue posible confirmar la cita. Intenta nuevamente.", alternatives: [], requiresDifferentDate: false });
        return;
      }
      const result = await readConfirmationResult(response);
      setSubmissionState({ kind: "success", result });
      setBookingStep("success");
    } catch {
      setSubmissionState({ kind: "error", message: "No fue posible confirmar la cita. Intenta nuevamente.", alternatives: [], requiresDifferentDate: false });
    }
  }

  function selectAlternative(start: string) {
    setSelectedStart(start);
    setBookingStep("appointment");
    resetConfirmation();
  }

  function editDetails() {
    setBookingStep("details");
    resetConfirmation();
  }

  function editAppointment() {
    setBookingStep("appointment");
    resetConfirmation();
  }

  return (
    <main className="booking-page">
      <header className="booking-header">
        <div className="booking-header__brand" aria-label="Manita de Gato, Salón de belleza">
          {publicView === "lookup" || bookingStep === "appointment" || bookingStep === "success" ? <img className="booking-header__logo" src="/assets/brand/logo.jpeg" alt="Manita de Gato" /> : null}
          <span className="booking-header__brand-name">Manita de Gato</span>
          <span className="booking-header__brand-kind">Salón de belleza</span>
        </div>
        <nav className="public-navigation" aria-label="Navegación principal">
          <button className={`public-navigation__item ${publicView === "booking" ? "public-navigation__item--current" : ""}`} aria-current={publicView === "booking" ? "page" : undefined} onClick={() => setPublicView("booking")} type="button">Reservar cita</button>
          <button className={`public-navigation__item ${publicView === "lookup" ? "public-navigation__item--current" : ""}`} aria-current={publicView === "lookup" ? "page" : undefined} onClick={() => setPublicView("lookup")} type="button">Consultar mi cita</button>
        </nav>
      </header>

      {publicView === "lookup" ? <PublicAppointmentLookup /> : <>
      <section className="booking-hero" aria-labelledby="booking-title">
        <p className="booking-hero__eyebrow">Reserva tu cita</p>
        <h1 id="booking-title">{bookingStep === "details" ? "Tus datos" : bookingStep === "confirm" ? "Confirma tu cita" : bookingStep === "success" ? "¡Tu cita ha sido reservada!" : "Tu belleza en buenas manos"}</h1>
        <p>{bookingStep === "details" ? "Estamos casi listas. Completa tu información para confirmar tu cita." : bookingStep === "confirm" ? "Revisa los detalles de tu cita. Si todo está correcto, confirma para finalizar." : bookingStep === "success" ? "Guarda tu código privado para consultar, modificar o cancelar tu cita." : "Sigue los pasos para agendar tu cita de forma rápida y sencilla."}</p>
      </section>

      <ol className="booking-steps" aria-label="Progreso de la reservación">
        <li className={`booking-steps__item ${bookingStep === "appointment" ? "booking-steps__item--current" : "booking-steps__item--complete"}`} aria-current={bookingStep === "appointment" ? "step" : undefined}>
          <span className="booking-steps__number">1</span>
          <span><strong>Tu cita</strong><small>Sucursal y servicio</small></span>
        </li>
        <li className={`booking-steps__item ${bookingStep === "details" ? "booking-steps__item--current" : bookingStep === "confirm" || bookingStep === "success" ? "booking-steps__item--complete" : ""}`} aria-current={bookingStep === "details" ? "step" : undefined}>
          <span className="booking-steps__number">2</span>
          <span><strong>Tus datos</strong><small>Información de contacto</small></span>
        </li>
        <li className={`booking-steps__item ${bookingStep === "confirm" ? "booking-steps__item--current" : bookingStep === "success" ? "booking-steps__item--complete" : ""}`} aria-current={bookingStep === "confirm" ? "step" : undefined}>
          <span className="booking-steps__number">3</span>
          <span><strong>Confirmar</strong><small>Revisa tu cita</small></span>
        </li>
      </ol>

      <section
        className={`booking-panel booking-panel--${bookingStep}`}
        aria-label={bookingStep === "success" ? "Confirmación de la reservación" : undefined}
        aria-labelledby={bookingStep === "success" ? undefined : "selection-title"}
      >
        {bookingStep !== "success" ? <div className="booking-panel__heading">
          <p className="booking-panel__step">{`Paso ${bookingStep === "details" ? "2" : bookingStep === "confirm" ? "3" : "1"} de 3`}</p>
          <h2 id="selection-title">{bookingStep === "details" ? "Información de contacto" : bookingStep === "confirm" ? "Revisión final" : "Selecciona tu cita"}</h2>
        </div> : null}

        {bookingStep === "appointment" ? <div className="booking-workspace">
        <div className="booking-form">
          <fieldset className="booking-fieldset">
            <legend>1. Selecciona tu sucursal</legend>
            <p className="booking-fieldset__hint">Elige la sucursal que te quede mejor.</p>
            <div className="branch-grid">
              {branches.map((item) => (
                <label
                  className={`selection-card ${branch === item.id ? "selection-card--selected" : ""}`}
                  key={item.id}
                >
                  <input checked={branch === item.id} name="branch" onChange={() => selectBranch(item.id)} type="radio" value={item.id} />
                  <span className="selection-card__content">
                    {item.image ? <img className="selection-card__image" src={item.image} alt={`Interior de la sucursal ${item.name}`} /> : <span className="selection-card__image selection-card__image--fallback" aria-hidden="true">♡</span>}
                    <span className="selection-card__title">{item.name}</span>
                    <span className="selection-card__description">Sucursal disponible</span>
                    <span className="selection-card__status">{branch === item.id ? "Seleccionada" : "Seleccionar"}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="booking-fieldset" disabled={branch === null}>
            <legend>2. Selecciona un servicio</legend>
            {branch === null ? <p className="booking-fieldset__hint">Primero selecciona una sucursal.</p> : null}
            <ServiceSelection
              branch={branch}
              onRetry={() => setRequestVersion((version) => version + 1)}
              onSelect={setSelectedService}
              selectedService={selectedService}
              state={serviceState}
            />
          </fieldset>

          <fieldset className="booking-fieldset" disabled={branch === null || selectedService === null}>
            <legend>3. Elige fecha y horario</legend>
            {branch === null || selectedService === null ? (
              <p className="booking-fieldset__hint">Primero selecciona una sucursal y un servicio.</p>
            ) : (
              <div className="schedule-layout">
                <div className="schedule-layout__calendar">
                <CalendarSelection selectedDate={selectedDate} onSelect={setSelectedDate} />
                <p className="booking-fieldset__hint">Puedes reservar desde una hora antes y hasta 90 días naturales.</p>
                </div>
                <div className="schedule-layout__times">
                <h3>4. Selecciona un horario</h3>
                <AvailabilitySelection
                  onRetry={() => setAvailabilityRequestVersion((version) => version + 1)}
                  onSelect={setSelectedStart}
                  selectedStart={selectedStart}
                  state={availabilityState}
                />
                </div>
              </div>
            )}
          </fieldset>

          {selectedStart !== null ? (
            <div className="booking-next-action">
              <p>Horario seleccionado: {formatStartTime(selectedStart)}.</p>
              <button className="booking-button booking-button--primary" onClick={() => setBookingStep("details")} type="button">Continuar</button>
            </div>
          ) : null}
        </div>
        <aside className="booking-aside" aria-label="Información de tu reservación">
          <div className="booking-aside__visual"><img src="/assets/brand/uñas.png" alt="Diseño de uñas del salón" /></div>
          <h3>Detalles que te hacen brillar</h3>
          <p>Agenda en línea de forma rápida, segura y desde cualquier lugar.</p>
          <SelectionSummary branch={branch} selectedService={selectedService} selectedStart={selectedStart} state={serviceState} />
          <div className="booking-aside__notice"><strong>Información importante</strong><p>Los horarios disponibles dependen del servicio y la sucursal seleccionados.</p></div>
        </aside>
        </div> : null}

        {bookingStep === "details" && selectedStart !== null ? (
          <div className="details-workspace">
            <fieldset className="booking-fieldset">
              <legend>Información de contacto</legend>
              <p className="booking-fieldset__hint">Necesitamos estos datos para gestionar y notificar tu cita.</p>
              <form className="customer-form" onSubmit={validateCustomerForm} noValidate>
                <div className="customer-form__grid">
                  <FormInput error={customerErrors.firstName} id="first-name" label="Nombre" onChange={(value) => updateCustomerField("firstName", value)} value={customerForm.firstName} />
                  <FormInput error={customerErrors.lastName} id="last-name" label="Apellido" onChange={(value) => updateCustomerField("lastName", value)} value={customerForm.lastName} />
                  <FormInput error={customerErrors.phone} id="phone" label="Número telefónico" onChange={(value) => updateCustomerField("phone", value)} type="tel" value={customerForm.phone} />
                  <FormInput error={customerErrors.email} id="email" label="Correo electrónico" onChange={(value) => updateCustomerField("email", value)} type="email" value={customerForm.email} />
                </div>
                <div className="consent-list" aria-describedby="consent-help">
                  <p id="consent-help" className="booking-fieldset__hint">Confirma las tres declaraciones para continuar.</p>
                  <ConsentCheckbox checked={customerForm.privacyNoticeAccepted} error={customerErrors.privacyNoticeAccepted} id="privacy-notice" label="Acepto el aviso de privacidad vigente." onChange={(value) => updateCustomerField("privacyNoticeAccepted", value)} />
                  <ConsentCheckbox checked={customerForm.contactProcessingAuthorized} error={customerErrors.contactProcessingAuthorized} id="contact-processing" label="Autorizo el uso de mis datos de contacto para gestionar y notificar esta cita." onChange={(value) => updateCustomerField("contactProcessingAuthorized", value)} />
                  <ConsentCheckbox checked={customerForm.adultResponsibilityDeclared} error={customerErrors.adultResponsibilityDeclared} id="adult-responsibility" label="Declaro que soy una persona adulta responsable de esta reservación." onChange={(value) => updateCustomerField("adultResponsibilityDeclared", value)} />
                </div>
                <div className="booking-flow-actions"><button className="booking-button" onClick={editAppointment} type="button">Regresar</button><button className="booking-button booking-button--primary" type="submit">Continuar a confirmación</button></div>
                {customerFormStatus !== null ? <p className="booking-state" role="status">{customerFormStatus}</p> : null}
              </form>
            </fieldset>
            <aside className="details-summary" aria-label="Resumen de tu cita">
              <div className="details-summary__heading"><span aria-hidden="true">◈</span><h3>Resumen de tu cita</h3></div>
              {selectedService ? <ServiceImage serviceName={selectedService} /> : null}
              <SelectionSummary branch={branch} selectedService={selectedService} selectedStart={selectedStart} state={serviceState} />
              <p className="details-summary__hint">Estos datos se usarán para confirmar tu cita y enviarte avisos.</p>
            </aside>
          </div>
        ) : null}

          {(bookingStep === "confirm" || bookingStep === "success") && branch !== null && selectedService !== null && selectedStart !== null ? (
            <ConfirmationPanel
              branch={branch}
              noticeState={privacyNoticeState}
              onConfirm={() => void confirmAppointment()}
              onEdit={editDetails}
              onSelectAlternative={selectAlternative}
              selectedService={selectedService}
              selectedStart={selectedStart}
              customerForm={customerForm}
              serviceState={serviceState}
              submissionState={submissionState}
            />
          ) : null}

        <p className="booking-panel__next-step" aria-live="polite">
          {bookingStep !== "appointment" ? "" : selectedService === null
            ? "Selecciona una fecha y un horario disponible para continuar."
            : selectedStart === null
              ? "Selecciona una fecha y un horario disponible para continuar."
              : "Horario seleccionado. Después ingresarás tus datos."}
        </p>
      </section>
      </>}
    </main>
  );
}

function ConfirmationPanel({ branch, customerForm, noticeState, onConfirm, onEdit, onSelectAlternative, selectedService, selectedStart, serviceState, submissionState }: {
  branch: Branch;
  customerForm: CustomerForm;
  noticeState: PrivacyNoticeState;
  onConfirm: () => void;
  onEdit: () => void;
  onSelectAlternative: (start: string) => void;
  selectedService: string;
  selectedStart: string;
  serviceState: ServiceState;
  submissionState: SubmissionState;
}) {
  const [copyFeedback, setCopyFeedback] = useState("");
  if (submissionState.kind === "success") {
    const { appointment, notifications, privateCode } = submissionState.result;
    const selectedServiceImage = appointment.serviceName;
    const copyPrivateCode = async () => {
      try {
        await navigator.clipboard.writeText(privateCode);
        setCopyFeedback("Código copiado");
      } catch {
        setCopyFeedback("No fue posible copiar el código");
      }
    };
    return (
      <div className="success-workspace">
        <section className="confirmation-panel success-panel" aria-label="Confirmación exitosa de cita">
          <div className="success-message"><span className="success-message__icon" aria-hidden="true">✓</span><div><p className="booking-panel__step">Cita confirmada</p><h2>Confirmación lista</h2><p>Guarda tu código privado para consultar tu cita.</p></div></div>
          <div className="private-code-card">
            <div><span className="private-code-card__label">Tu código de cita</span><p className="private-code" aria-label="Código privado">{privateCode}</p></div>
            <button className="booking-button" onClick={() => void copyPrivateCode()} type="button">Copiar</button>
            <p className="private-code-card__personal"><span aria-hidden="true">⌑</span> Este código es personal.</p>
            <p className="copy-feedback" aria-live="polite">{copyFeedback}</p>
          </div>
          <section className="success-details" aria-labelledby="success-details-title">
            <h3 id="success-details-title">Detalles de tu cita</h3>
            <div className="success-details__content"><ServiceImage serviceName={selectedServiceImage} /><div className="success-details__info"><h4>{appointment.serviceName}</h4><dl><div><dt>Fecha</dt><dd>{formatAppointmentDate(appointment.scheduledStart)}</dd></div><div><dt>Horario</dt><dd>{formatStartTime(appointment.scheduledStart)}</dd></div><div><dt>Sucursal</dt><dd>{formatBranch(appointment.branch)}</dd></div>{appointment.durationMinutes !== undefined ? <div><dt>Duración</dt><dd>{formatDuration(appointment.durationMinutes)}</dd></div> : null}{appointment.price !== undefined ? <div><dt>Precio</dt><dd>${appointment.price} MXN</dd></div> : null}{appointment.status !== undefined ? <div><dt>Estado</dt><dd>{formatAppointmentStatus(appointment.status)}</dd></div> : null}</dl></div></div>
          </section>
        </section>
        <aside className="success-aside" aria-label="Estado de la confirmación">
          <NotificationStatuses notifications={notifications} />
          <section className="success-thanks"><img src="/assets/brand/logo.jpeg" alt="Manita de Gato" /><div><h3>¡Gracias por ser parte de nuestra historia!</h3><p>Tu belleza, nuestra pasión.</p></div></section>
        </aside>
      </div>
    );
  }

  const selected = serviceState.kind === "ready" ? serviceState.services.find((service) => service.name === selectedService) : undefined;
  return (
    <div className="confirm-workspace">
    <section className="confirmation-panel" aria-labelledby="confirmation-title">
      <p className="booking-panel__step">Paso 3 de 3</p>
      <h2 id="confirmation-title">Resumen de tu cita</h2>
      <div className="confirm-service">
        <ServiceImage serviceName={selectedService} />
        <div><h3>{selectedService}</h3>{selected ? <p>{formatDuration(selected.duration_minutes)} · ${selected.price} MXN</p> : null}</div>
      </div>
      <AppointmentSummary appointment={{ serviceName: selectedService, branch, scheduledStart: selectedStart, durationMinutes: selected?.duration_minutes, price: selected?.price }} />
      <section className="confirm-details" aria-labelledby="confirm-details-title"><h3 id="confirm-details-title">Tus datos</h3><dl><div><dt>Nombre</dt><dd>{customerForm.firstName} {customerForm.lastName}</dd></div><div><dt>Teléfono</dt><dd>{customerForm.phone}</dd></div><div><dt>Correo electrónico</dt><dd>{customerForm.email}</dd></div></dl></section>
      <section className="confirm-consents" aria-labelledby="confirm-consents-title"><h3 id="confirm-consents-title">Confirmaciones y avisos</h3><ul><li>Aviso de privacidad aceptado</li><li>Autorización de contacto confirmada</li><li>Declaración de mayoría de edad confirmada</li></ul></section>
      {noticeState.kind === "loading" ? <p className="booking-state" role="status">Cargando el aviso de privacidad…</p> : null}
      {noticeState.kind === "error" ? <p className="booking-state booking-state--error" role="alert">No fue posible preparar la confirmación de tu cita.</p> : null}
      {noticeState.kind === "ready" ? (
        <details className="privacy-notice">
          <summary>Leer aviso de privacidad vigente</summary>
          <p>{noticeState.notice.content}</p>
          <p>Versión: {noticeState.notice.version}</p>
        </details>
      ) : null}
      {submissionState.kind === "error" ? (
        <div className="booking-state booking-state--error" role="alert">
          <p>{submissionState.message}</p>
          {submissionState.alternatives.length > 0 ? (
            <div className="alternative-list" aria-label="Horarios alternativos">
              <p>Estos horarios siguen disponibles el mismo día:</p>
              {submissionState.alternatives.map((start) => <button className="booking-button" key={start} onClick={() => onSelectAlternative(start)} type="button">{formatStartTime(start)}</button>)}
            </div>
          ) : submissionState.requiresDifferentDate ? <p>Elige otra fecha para continuar.</p> : null}
        </div>
      ) : null}
      <div className="confirmation-actions">
        <button className="booking-button" disabled={submissionState.kind === "submitting"} onClick={onEdit} type="button">Corregir datos</button>
        <button className="booking-button booking-button--primary" disabled={noticeState.kind !== "ready" || submissionState.kind === "submitting"} onClick={onConfirm} type="button">{submissionState.kind === "submitting" ? "Confirmando cita…" : "Confirmar mi cita"}</button>
      </div>
    </section>
    <aside className="confirm-aside" aria-label="Orientación para confirmar tu cita">
      <div className="confirm-aside__visual"><img src="/assets/brand/uñas.png" alt="Diseño de uñas del salón" /></div>
      <h3>¡Todo listo!</h3><p>Revisa la información y confirma tu reservación.</p>
      <section><h4>¿Qué sigue?</h4><ol><li><strong>Confirma tu cita.</strong></li><li><strong>Recibirás la información</strong> por los canales disponibles.</li><li><strong>Guarda tu código privado</strong> para gestionar tu cita.</li></ol></section>
      <section className="confirm-aside__notice"><h4>Información importante</h4><p>Las citas pueden reservarse entre 60 minutos y 90 días antes. El horario de atención es de 9:00 a 19:00.</p></section>
    </aside>
    </div>
  );
}

function SelectionSummary({ branch, selectedService, selectedStart, state }: {
  branch: Branch | null;
  selectedService: string | null;
  selectedStart: string | null;
  state: ServiceState;
}) {
  const selected = state.kind === "ready" ? state.services.find((service) => service.name === selectedService) : undefined;
  return (
    <dl className="selection-summary">
      <div><dt>Sucursal</dt><dd>{branch === null ? "Por seleccionar" : formatBranch(branch)}</dd></div>
      <div><dt>Servicio</dt><dd>{selectedService ?? "Por seleccionar"}</dd></div>
      {selected ? <div><dt>Duración y precio</dt><dd>{formatDuration(selected.duration_minutes)} · ${selected.price} MXN</dd></div> : null}
      <div><dt>Horario</dt><dd>{selectedStart === null ? "Por seleccionar" : formatAppointmentDateTime(selectedStart)}</dd></div>
    </dl>
  );
}

function AppointmentSummary({ appointment }: { appointment: Partial<ConfirmationResult["appointment"]> }) {
  return (
    <dl className="appointment-summary">
      <div><dt>Servicio</dt><dd>{appointment.serviceName}</dd></div>
      <div><dt>Sucursal</dt><dd>{formatBranch(appointment.branch)}</dd></div>
      <div><dt>Fecha y horario</dt><dd>{appointment.scheduledStart ? formatAppointmentDateTime(appointment.scheduledStart) : ""}</dd></div>
      {appointment.durationMinutes !== undefined ? <div><dt>Duración</dt><dd>{formatDuration(appointment.durationMinutes)}</dd></div> : null}
      {appointment.price !== undefined ? <div><dt>Precio</dt><dd>${appointment.price} MXN</dd></div> : null}
      {appointment.status !== undefined ? <div><dt>Estado</dt><dd>{formatAppointmentStatus(appointment.status)}</dd></div> : null}
    </dl>
  );
}

function NotificationStatuses({ notifications }: { notifications: ConfirmationResult["notifications"] }) {
  return (
    <section className="notification-statuses" aria-labelledby="notification-statuses-title">
      <h3 id="notification-statuses-title">Estado de notificaciones</h3>
      <ul>{notifications.map((notification) => <li key={notification.channel}>{formatChannel(notification.channel)}: {formatNotificationStatus(notification.status)}</li>)}</ul>
    </section>
  );
}

function FormInput({ error, id, label, onChange, type = "text", value }: {
  error?: string;
  id: string;
  label: string;
  onChange: (value: string) => void;
  type?: "email" | "tel" | "text";
  value: string;
}) {
  const errorId = `${id}-error`;
  return (
    <label className="form-control" htmlFor={id}>
      <span>{label}</span>
      <input aria-describedby={error ? errorId : undefined} aria-invalid={error ? "true" : "false"} className="booking-input" id={id} onChange={(event) => onChange(event.target.value)} type={type} value={value} />
      {error ? <span className="form-error" id={errorId} role="alert">{error}</span> : null}
    </label>
  );
}

function ConsentCheckbox({ checked, error, id, label, onChange }: {
  checked: boolean;
  error?: string;
  id: string;
  label: string;
  onChange: (value: boolean) => void;
}) {
  const errorId = `${id}-error`;
  return (
    <label className="consent-control" htmlFor={id}>
      <input aria-describedby={error ? errorId : undefined} aria-invalid={error ? "true" : "false"} checked={checked} id={id} onChange={(event) => onChange(event.target.checked)} type="checkbox" />
      <span>{label}</span>
      {error ? <span className="form-error" id={errorId} role="alert">{error}</span> : null}
    </label>
  );
}

function CalendarSelection({ onSelect, selectedDate }: { onSelect: (date: string) => void; selectedDate: string }) {
  const minimum = minBookingDate();
  const maximum = maxBookingDate();
  const selected = selectedDate || minimum;
  const selectedParts = selected.split("-").map(Number);
  const [monthCursor, setMonthCursor] = useState(`${selectedParts[0] || new Date().getFullYear()}-${String(selectedParts[1] || new Date().getMonth() + 1).padStart(2, "0")}`);
  const cursorParts = monthCursor.split("-").map(Number);
  const monthDate = new Date(cursorParts[0], (cursorParts[1] || 1) - 1, 1);
  const firstWeekday = monthDate.getDay();
  const daysInMonth = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0).getDate();
  const monthKey = `${monthDate.getFullYear()}-${String(monthDate.getMonth() + 1).padStart(2, "0")}`;
  const minMonth = minimum.slice(0, 7);
  const maxMonth = maximum.slice(0, 7);
  const canGoPrevious = monthKey > minMonth;
  const canGoNext = monthKey < maxMonth;
  const moveMonth = (offset: number) => {
    const next = new Date(monthDate.getFullYear(), monthDate.getMonth() + offset, 1);
    const nextKey = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
    if (nextKey >= minMonth && nextKey <= maxMonth) setMonthCursor(nextKey);
  };
  const cells: Array<number | null> = [...Array.from({ length: firstWeekday }, () => null), ...Array.from({ length: daysInMonth }, (_, index) => index + 1)];
  while (cells.length % 7 !== 0) cells.push(null);
  return (
    <div className="calendar" role="group" aria-label="Selecciona la fecha de la cita">
      <div className="calendar__header">
        <button className="calendar__nav" aria-label="Mes anterior" disabled={!canGoPrevious} onClick={() => moveMonth(-1)} type="button">‹</button>
        <p aria-live="polite">{new Intl.DateTimeFormat("es-MX", { month: "long", year: "numeric" }).format(monthDate)}</p>
        <button className="calendar__nav" aria-label="Mes siguiente" disabled={!canGoNext} onClick={() => moveMonth(1)} type="button">›</button>
      </div>
      <div className="calendar__weekdays" aria-hidden="true">{["D", "L", "M", "M", "J", "V", "S"].map((day, index) => <span key={`${day}-${index}`}>{day}</span>)}</div>
      <div className="calendar__grid" role="grid" aria-label={monthKey}>
        {cells.map((day, index) => {
          if (day === null) return <span className="calendar__empty" key={`empty-${index}`} aria-hidden="true" />;
          const date = `${monthKey}-${String(day).padStart(2, "0")}`;
          const disabled = date < minimum || date > maximum;
          return <button className={`calendar__day ${selectedDate === date ? "calendar__day--selected" : ""}`} aria-label={new Intl.DateTimeFormat("es-MX", { dateStyle: "long" }).format(new Date(`${date}T12:00:00`))} aria-selected={selectedDate === date} disabled={disabled} key={date} onClick={() => onSelect(date)} role="gridcell" type="button">{day}</button>;
        })}
      </div>
      <p className="booking-fieldset__hint">Elige una fecha entre hoy y los próximos 90 días.</p>
    </div>
  );
}

function AvailabilitySelection({ onRetry, onSelect, selectedStart, state }: {
  onRetry: () => void;
  onSelect: (start: string) => void;
  selectedStart: string | null;
  state: AvailabilityState;
}) {
  if (state.kind === "idle") return null;
  if (state.kind === "loading") return <p className="booking-state" role="status">Cargando horarios disponibles…</p>;
  if (state.kind === "error") {
    return <div className="booking-state booking-state--error" role="alert"><p>No fue posible consultar los horarios disponibles.</p><button className="booking-button" onClick={onRetry} type="button">Reintentar</button></div>;
  }
  if (state.starts.length === 0) return <p className="booking-state" role="status">No hay horarios disponibles para esta fecha. Elige otra fecha.</p>;
  return (
    <div className="availability-grid" role="radiogroup" aria-label="Horarios disponibles">
      {state.starts.map((start) => (
        <label className={`time-card ${selectedStart === start ? "time-card--selected" : ""}`} key={start}>
          <input checked={selectedStart === start} name="appointment-start" onChange={() => onSelect(start)} type="radio" value={start} />
          <span className="time-card__content">
            <span>{formatStartTime(start)}</span>
            <span className="time-card__status">{selectedStart === start ? "Seleccionado" : "Disponible"}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

function ServiceSelection({ branch, onRetry, onSelect, selectedService, state }: {
  branch: Branch | null;
  onRetry: () => void;
  onSelect: (serviceName: string) => void;
  selectedService: string | null;
  state: ServiceState;
}) {
  if (branch === null || state.kind === "idle") return null;
  if (state.kind === "loading") return <p className="booking-state" role="status">Cargando servicios disponibles…</p>;
  if (state.kind === "error") {
    return <div className="booking-state booking-state--error" role="alert"><p>No fue posible cargar los servicios disponibles.</p><button className="booking-button" onClick={onRetry} type="button">Reintentar</button></div>;
  }
  if (state.services.length === 0) return <p className="booking-state" role="status">No hay servicios disponibles en esta sucursal por el momento.</p>;

  return (
    <div className="service-grid" role="radiogroup" aria-label="Servicios disponibles">
      {state.services.map((service) => (
        <label className={`service-card ${selectedService === service.name ? "service-card--selected" : ""}`} key={service.name}>
          <input checked={selectedService === service.name} name="service" onChange={() => onSelect(service.name)} type="radio" value={service.name} />
          <span className="service-card__content">
            <ServiceImage serviceName={service.name} />
            <span className="service-card__name">{service.name}</span>
            <span className="service-card__details">{formatDuration(service.duration_minutes)} · ${service.price} MXN</span>
            <span className="service-card__status">{selectedService === service.name ? "Seleccionado" : "Seleccionar"}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

function ServiceImage({ serviceName }: { serviceName: string }) {
  const normalized = serviceName.toLocaleLowerCase("es-MX");
  const image = normalized.includes("uña") || normalized.includes("manicure") || normalized.includes("gel") ? "/assets/brand/uñas.png" : normalized.includes("pestaña") ? "/assets/brand/pestañas.png" : normalized.includes("cabello") || normalized.includes("corte") || normalized.includes("tinte") || normalized.includes("peinado") ? "/assets/brand/cabello.png" : null;
  return image ? <img className="service-card__image" src={image} alt="" aria-hidden="true" /> : <span className="service-card__image service-card__image--fallback" aria-hidden="true">✦</span>;
}

async function loadServices(branch: Branch, signal: AbortSignal): Promise<PublicService[]> {
  const response = await fetch(`/api/public/services?branch=${branch}`, { signal });
  if (!response.ok) throw new Error("Unable to load public services.");
  const payload: unknown = await response.json();
  if (!Array.isArray(payload) || !payload.every(isPublicService)) throw new Error("Public service response has an invalid shape.");
  return payload;
}

async function loadAvailability(branch: Branch, service: string, appointmentDate: string, signal: AbortSignal): Promise<string[]> {
  const params = new URLSearchParams({ branch, service, date: appointmentDate });
  const response = await fetch(`/api/public/availability?${params.toString()}`, { signal });
  if (!response.ok) throw new Error("Unable to load public availability.");
  const payload: unknown = await response.json();
  if (typeof payload !== "object" || payload === null) throw new Error("Public availability response has an invalid shape.");
  const record = payload as Record<string, unknown>;
  if (!Array.isArray(record.starts) || !record.starts.every((value: unknown) => typeof value === "string")) {
    throw new Error("Public availability response has an invalid shape.");
  }
  return record.starts as string[];
}

async function loadPrivacyNotice(signal: AbortSignal): Promise<PublicPrivacyNotice> {
  const response = await fetch("/api/public/privacy-notice", { signal });
  if (!response.ok) throw new Error("Unable to load the public privacy notice.");
  const payload: unknown = await response.json();
  if (!isPublicPrivacyNotice(payload)) throw new Error("Public privacy notice response has an invalid shape.");
  return payload;
}

async function issueConfirmationReference(): Promise<string> {
  const response = await fetch("/api/public/booking-confirmation-references", { method: "POST" });
  if (!response.ok) throw new Error("Unable to issue a booking confirmation reference.");
  const payload: unknown = await response.json();
  if (typeof payload !== "object" || payload === null || typeof (payload as Record<string, unknown>).confirmationReference !== "string") {
    throw new Error("Booking confirmation reference response has an invalid shape.");
  }
  return (payload as { confirmationReference: string }).confirmationReference;
}

async function readConfirmationResult(response: Response): Promise<ConfirmationResult> {
  const payload: unknown = await response.json();
  if (!isConfirmationResult(payload)) throw new Error("Public appointment confirmation response has an invalid shape.");
  return payload;
}

async function readConflict(response: Response): Promise<{ message: string; alternatives: string[]; requiresDifferentDate: boolean }> {
  const payload: unknown = await response.json();
  if (typeof payload !== "object" || payload === null) return { message: "El horario seleccionado ya no está disponible.", alternatives: [], requiresDifferentDate: false };
  const conflict = payload as Record<string, unknown>;
  return {
    message: typeof conflict.detail === "string" ? conflict.detail : "El horario seleccionado ya no está disponible.",
    alternatives: Array.isArray(conflict.alternatives) && conflict.alternatives.every((value) => typeof value === "string") ? conflict.alternatives : [],
    requiresDifferentDate: conflict.requiresDifferentDate === true,
  };
}

function isPublicPrivacyNotice(value: unknown): value is PublicPrivacyNotice {
  if (typeof value !== "object" || value === null) return false;
  const notice = value as Record<string, unknown>;
  return typeof notice.version === "string" && typeof notice.content === "string";
}

function isConfirmationResult(value: unknown): value is ConfirmationResult {
  if (typeof value !== "object" || value === null) return false;
  const result = value as Record<string, unknown>;
  if (typeof result.privateCode !== "string" || typeof result.appointment !== "object" || result.appointment === null || !Array.isArray(result.notifications)) return false;
  const appointment = result.appointment as Record<string, unknown>;
  return typeof appointment.serviceName === "string" && typeof appointment.branch === "string" && typeof appointment.scheduledStart === "string" && typeof appointment.durationMinutes === "number" && typeof appointment.price === "string" && typeof appointment.status === "string" && result.notifications.every(isNotificationStatus);
}

function isNotificationStatus(value: unknown): value is { channel: string; status: string } {
  return typeof value === "object" && value !== null && typeof (value as Record<string, unknown>).channel === "string" && typeof (value as Record<string, unknown>).status === "string";
}

function isPublicService(value: unknown): value is PublicService {
  if (typeof value !== "object" || value === null) return false;
  const service = value as Record<string, unknown>;
  return typeof service.name === "string" && typeof service.duration_minutes === "number" && typeof service.price === "string";
}

function validateCustomerData(form: CustomerForm): CustomerErrors {
  const errors: CustomerErrors = {};
  if (!isValidName(form.firstName)) errors.firstName = "Escribe un nombre válido de 1 a 100 caracteres.";
  if (!isValidName(form.lastName)) errors.lastName = "Escribe un apellido válido de 1 a 100 caracteres.";
  if (normalizePhone(form.phone) === null) errors.phone = "Escribe un número mexicano válido de 10 dígitos.";
  if (!isValidEmail(form.email)) errors.email = "Escribe un correo electrónico válido.";
  if (!form.privacyNoticeAccepted) errors.privacyNoticeAccepted = "Debes aceptar el aviso de privacidad.";
  if (!form.contactProcessingAuthorized) errors.contactProcessingAuthorized = "Debes autorizar el uso de tus datos de contacto.";
  if (!form.adultResponsibilityDeclared) errors.adultResponsibilityDeclared = "Debes declarar que eres una persona adulta responsable.";
  return errors;
}

function isValidName(value: string): boolean {
  const normalized = value.trim();
  return normalized.length >= 1 && normalized.length <= 100 && /^[\p{L}]+(?:[\p{L}\s'’-]*[\p{L}])?$/u.test(normalized);
}

function normalizePhone(value: string): string | null {
  let normalized = value.trim();
  if (normalized.startsWith("+52")) normalized = normalized.slice(3);
  const digits = normalized.replace(/[\s()-]/g, "");
  return /^\d{10}$/.test(digits) ? digits : null;
}

function isValidEmail(value: string): boolean {
  const normalized = value.trim();
  if (normalized.length < 1 || normalized.length > 254 || (normalized.match(/@/g) ?? []).length !== 1) return false;
  const [local, domain] = normalized.split("@");
  if (!/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$/.test(local) || local.startsWith(".") || local.endsWith(".") || local.includes("..")) return false;
  const segments = domain.split(".");
  return segments.length >= 2 && segments.every((segment) => /^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$/.test(segment)) && /^[A-Za-z]{2,}$/.test(segments.at(-1) ?? "");
}

function formatDuration(minutes: number): string {
  if (minutes === 60) return "1 hora";
  if (minutes % 60 === 0) return `${minutes / 60} horas`;
  return `${minutes} minutos`;
}

function formatStartTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Horario no disponible";
  return new Intl.DateTimeFormat("es-MX", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "America/Mexico_City" }).format(parsed);
}

function formatAppointmentDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "long", timeStyle: "short", timeZone: "America/Mexico_City" }).format(parsed);
}

function formatAppointmentDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "long", timeZone: "America/Mexico_City" }).format(parsed);
}

function formatBranch(branch: string | undefined): string {
  return branch === "chiconcuac" ? "Chiconcuac" : branch === "texcoco" ? "Texcoco" : "";
}

function formatAppointmentStatus(status: string): string {
  return status === "scheduled" ? "Programada" : status;
}

function formatChannel(channel: string): string {
  return channel === "whatsapp" ? "WhatsApp" : channel === "email" ? "Correo" : channel;
}

function formatNotificationStatus(status: string): string {
  return status === "accepted" ? "Aceptada por el proveedor" : status === "pending" ? "Pendiente" : status === "failed" ? "No fue posible enviar" : status;
}

function minBookingDate(): string {
  return toIsoDate(new Date());
}

function maxBookingDate(): string {
  const date = new Date();
  date.setDate(date.getDate() + 90);
  return toIsoDate(date);
}

function toIsoDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
