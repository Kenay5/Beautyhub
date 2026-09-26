import { FormEvent, useState } from "react";

import {
  AdministrativeSessionUnavailableError,
  RecoveryCodeRegenerationError,
  regenerateAdministrativeRecoveryCodes,
} from "./adminSessionClient";

export function RecoveryCodeRegenerationPanel({
  csrfToken,
  onSessionUnavailable,
  onRegenerated,
}: {
  csrfToken: string;
  onSessionUnavailable: () => void;
  onRegenerated: (codes: string[]) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [credentialError, setCredentialError] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setFeedback(null);
    setCredentialError(false);
    try {
      const recoveryCodes = await regenerateAdministrativeRecoveryCodes({
        currentPassword,
        totpCode,
        csrfToken,
      });
      onRegenerated(recoveryCodes);
    } catch (error) {
      if (error instanceof AdministrativeSessionUnavailableError) {
        onSessionUnavailable();
        return;
      }
      setCredentialError(
        error instanceof RecoveryCodeRegenerationError &&
          error.kind === "credentials",
      );
      setFeedback(
        error instanceof RecoveryCodeRegenerationError
          ? {
              credentials: "No fue posible comprobar las credenciales.",
              forbidden: "No tienes permiso para realizar esta operación.",
              unavailable: "No fue posible regenerar los códigos. Inténtalo de nuevo.",
            }[error.kind]
          : "No fue posible regenerar los códigos. Inténtalo de nuevo.",
      );
    } finally {
      setCurrentPassword("");
      setTotpCode("");
      setSubmitting(false);
    }
  }

  return (
    <section className="staff-access-card" aria-labelledby="recovery-code-regeneration-title">
      <h2 id="recovery-code-regeneration-title">Regenerar códigos de recuperación</h2>
      <p>
        Confirma tu contraseña actual y el código de tu aplicación de autenticación.
        Los códigos actuales dejarán de funcionar y tu sesión se cerrará.
      </p>
      <form className="staff-access-form" onSubmit={(event) => void submit(event)}>
        <label htmlFor="regenerate-recovery-current-password">Contraseña actual para regenerar códigos</label>
        <input
          id="regenerate-recovery-current-password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={128}
          aria-describedby={credentialError ? "recovery-code-regeneration-feedback" : undefined}
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
        />
        <label htmlFor="regenerate-recovery-totp">Código temporal para regenerar códigos</label>
        <input
          id="regenerate-recovery-totp"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          maxLength={32}
          aria-describedby={credentialError ? "recovery-code-regeneration-feedback" : undefined}
          value={totpCode}
          onChange={(event) => setTotpCode(event.target.value)}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Regenerando…" : "Regenerar códigos"}
        </button>
      </form>
      {feedback ? (
        <p id="recovery-code-regeneration-feedback" role="alert">{feedback}</p>
      ) : null}
    </section>
  );
}
