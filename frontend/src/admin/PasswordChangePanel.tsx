import { FormEvent, useState } from "react";

import {
  AdministrativePasswordChangeError,
  AdministrativeSessionUnavailableError,
  changeAdministrativePassword,
} from "./adminSessionClient";

export function PasswordChangePanel({
  csrfToken,
  onSessionUnavailable,
  onPasswordChanged,
}: {
  csrfToken: string;
  onSessionUnavailable: () => void;
  onPasswordChanged: () => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<"credentials" | "password" | "other" | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setFeedback(null);
    setErrorKind(null);
    try {
      await changeAdministrativePassword({
        currentPassword,
        totpCode,
        newPassword,
        csrfToken,
      });
      onPasswordChanged();
    } catch (error) {
      if (error instanceof AdministrativeSessionUnavailableError) {
        onSessionUnavailable();
        return;
      }
      setErrorKind(
        error instanceof AdministrativePasswordChangeError &&
        (error.kind === "credentials" || error.kind === "password")
          ? error.kind
          : "other",
      );
      setFeedback(
        error instanceof AdministrativePasswordChangeError
          ? {
              credentials: "No fue posible comprobar las credenciales.",
              password: "La nueva contraseña no es válida. Usa entre 12 y 128 caracteres y evita contraseñas comunes.",
              forbidden: "No tienes permiso para realizar esta operación.",
              unavailable: "No fue posible cambiar la contraseña. Inténtalo de nuevo.",
            }[error.kind]
          : "No fue posible cambiar la contraseña. Inténtalo de nuevo.",
      );
    } finally {
      setCurrentPassword("");
      setTotpCode("");
      setNewPassword("");
      setSubmitting(false);
    }
  }

  return (
    <section className="staff-access-card" aria-labelledby="password-change-title">
      <h2 id="password-change-title">Cambiar contraseña</h2>
      <p>Confirma tu contraseña actual y el código de tu aplicación de autenticación.</p>
      <form className="staff-access-form" onSubmit={(event) => void submit(event)}>
        <label htmlFor="current-admin-password">Contraseña actual</label>
        <input
          id="current-admin-password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={128}
          aria-describedby={errorKind === "credentials" ? "password-change-feedback" : undefined}
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
        />
        <label htmlFor="change-password-totp">Código de 6 dígitos</label>
        <input
          id="change-password-totp"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          maxLength={32}
          aria-describedby={errorKind === "credentials" ? "password-change-feedback" : undefined}
          value={totpCode}
          onChange={(event) => setTotpCode(event.target.value)}
        />
        <label htmlFor="new-admin-password">Nueva contraseña</label>
        <input
          id="new-admin-password"
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          maxLength={128}
          aria-describedby={errorKind === "password" ? "password-change-feedback" : undefined}
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Guardando…" : "Cambiar contraseña"}
        </button>
      </form>
      {feedback ? <p id="password-change-feedback" role="alert">{feedback}</p> : null}
    </section>
  );
}
