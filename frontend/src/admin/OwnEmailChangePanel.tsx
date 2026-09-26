import { FormEvent, useState } from "react";

import {
  AdministrativeSessionUnavailableError,
  OwnEmailChangeError,
  requestOwnAdministrativeEmailChange,
} from "./adminSessionClient";

export function OwnEmailChangePanel({
  csrfToken,
  onSessionUnavailable,
}: {
  csrfToken: string;
  onSessionUnavailable: () => void;
}) {
  const [newEmail, setNewEmail] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setFeedback(null);
    try {
      await requestOwnAdministrativeEmailChange({
        newEmail,
        currentPassword,
        totpCode,
        csrfToken,
      });
      setFeedback("Revisa el correo nuevo para confirmar. Tu correo actual sigue activo hasta entonces.");
    } catch (error) {
      if (error instanceof AdministrativeSessionUnavailableError) {
        onSessionUnavailable();
        return;
      }
      setFeedback(
        error instanceof OwnEmailChangeError
          ? {
              credentials: "No fue posible comprobar las credenciales.",
              email: "Escribe un correo con formato válido.",
              forbidden: "No tienes permiso para realizar esta operación.",
              unavailable: "No fue posible reservar el correo solicitado.",
              delivery: "No se pudo enviar el enlace. Tu correo actual sigue activo. Inténtalo de nuevo.",
            }[error.kind]
          : "No fue posible solicitar el cambio de correo. Inténtalo de nuevo.",
      );
    } finally {
      setCurrentPassword("");
      setTotpCode("");
      setSubmitting(false);
    }
  }

  return (
    <section className="staff-access-card" aria-labelledby="own-email-change-title">
      <h2 id="own-email-change-title">Solicitar cambio de correo</h2>
      <p>Confirma tu contraseña y el código de tu aplicación. Tu correo actual no cambiará durante esta solicitud.</p>
      <form className="staff-access-form own-email-change-form" onSubmit={(event) => void submit(event)}>
        <label htmlFor="own-email-change-new-email">Correo nuevo</label>
        <input
          id="own-email-change-new-email"
          type="email"
          autoComplete="email"
          required
          maxLength={254}
          value={newEmail}
          onChange={(event) => setNewEmail(event.target.value)}
        />
        <label htmlFor="own-email-change-password">Contraseña actual</label>
        <input
          id="own-email-change-password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={128}
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
        />
        <label htmlFor="own-email-change-totp">Código de 6 dígitos</label>
        <input
          id="own-email-change-totp"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          maxLength={32}
          value={totpCode}
          onChange={(event) => setTotpCode(event.target.value)}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Comprobando…" : "Reservar correo"}
        </button>
      </form>
      {feedback ? <p role="status">{feedback}</p> : null}
    </section>
  );
}
