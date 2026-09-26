import { FormEvent, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

import {
  AdministrativeSessionUnavailableError,
  PreparedAdministrativeTotpReplacement,
  TotpReplacementConfirmationError,
  TotpReplacementPreparationError,
  confirmAdministrativeTotpReplacement,
  prepareAdministrativeTotpReplacement,
} from "./adminSessionClient";

export function TotpReplacementPanel({
  csrfToken,
  onSessionUnavailable,
  onReplaced,
}: {
  csrfToken: string;
  onSessionUnavailable: () => void;
  onReplaced: (codes: string[]) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [factorKind, setFactorKind] = useState<"totp" | "recovery">("totp");
  const [factorCode, setFactorCode] = useState("");
  const [setup, setSetup] = useState<PreparedAdministrativeTotpReplacement | null>(null);
  const [setupExpiresAt, setSetupExpiresAt] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [credentialError, setCredentialError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [confirmationCode, setConfirmationCode] = useState("");

  useEffect(() => {
    if (setupExpiresAt === null) return;
    const timeout = window.setTimeout(() => {
      setSetup(null);
      setSetupExpiresAt(null);
      setFeedback("La configuración pendiente venció. Vuelve a comprobar tus credenciales para iniciar otra.");
    }, Math.max(0, setupExpiresAt - Date.now()));
    return () => window.clearTimeout(timeout);
  }, [setupExpiresAt]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setSetup(null);
    setSetupExpiresAt(null);
    setFeedback(null);
    setCredentialError(false);
    try {
      const prepared = await prepareAdministrativeTotpReplacement({
        currentPassword,
        ...(factorKind === "totp" ? { totpCode: factorCode } : { recoveryCode: factorCode }),
        csrfToken,
      });
      setSetup(prepared);
      setSetupExpiresAt(Date.now() + 30 * 60 * 1000);
    } catch (error) {
      if (error instanceof AdministrativeSessionUnavailableError) {
        onSessionUnavailable();
        return;
      }
      setCredentialError(
        error instanceof TotpReplacementPreparationError && error.kind === "credentials",
      );
      setFeedback(
        error instanceof TotpReplacementPreparationError
          ? {
              credentials: "No fue posible comprobar las credenciales.",
              forbidden: "No tienes permiso para realizar esta operación.",
              unavailable: "No fue posible iniciar la configuración. Inténtalo de nuevo.",
            }[error.kind]
          : "No fue posible iniciar la configuración. Inténtalo de nuevo.",
      );
    } finally {
      setCurrentPassword("");
      setFactorCode("");
      setSubmitting(false);
    }
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setFeedback(null);
    try {
      const codes = await confirmAdministrativeTotpReplacement({
        totpCode: confirmationCode,
        csrfToken,
      });
      setSetup(null);
      setSetupExpiresAt(null);
      onReplaced(codes);
    } catch (error) {
      if (error instanceof AdministrativeSessionUnavailableError) {
        onSessionUnavailable();
        return;
      }
      setSetup(null);
      setSetupExpiresAt(null);
      setCredentialError(error instanceof TotpReplacementConfirmationError && error.kind === "credentials");
      setFeedback(
        error instanceof TotpReplacementConfirmationError && error.kind === "credentials"
          ? "No fue posible comprobar el código. La configuración pendiente se descartó; inicia una nueva preparación."
          : "No fue posible confirmar el reemplazo. Inicia una nueva preparación.",
      );
    } finally {
      setConfirmationCode("");
      setSubmitting(false);
    }
  }

  return (
    <section className="staff-access-card" aria-labelledby="totp-replacement-title">
      <h2 id="totp-replacement-title">Reemplazar aplicación de autenticación</h2>
      <p>
        Comprueba tu contraseña y el segundo factor actual. La configuración nueva no
        sustituirá la anterior hasta que se confirme en el siguiente paso.
      </p>
      <form className="staff-access-form" onSubmit={(event) => void submit(event)}>
        <label htmlFor="replace-totp-current-password">Contraseña actual para reemplazar el factor</label>
        <input
          id="replace-totp-current-password"
          type="password"
          autoComplete="current-password"
          required
          maxLength={128}
          aria-describedby={credentialError ? "totp-replacement-feedback" : undefined}
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
        />
        <fieldset className="admin-factor-options">
          <legend>Segundo factor actual</legend>
          <label>
            <input
              type="radio"
              name="totp-replacement-factor"
              checked={factorKind === "totp"}
              onChange={() => { setFactorKind("totp"); setFactorCode(""); }}
            />
            Código de la aplicación
          </label>
          <label>
            <input
              type="radio"
              name="totp-replacement-factor"
              checked={factorKind === "recovery"}
              onChange={() => { setFactorKind("recovery"); setFactorCode(""); }}
            />
            Código de recuperación
          </label>
        </fieldset>
        <label htmlFor="replace-totp-factor-proof">
          {factorKind === "totp" ? "Código temporal actual" : "Código de recuperación actual"}
        </label>
        <input
          id="replace-totp-factor-proof"
          type="text"
          inputMode={factorKind === "totp" ? "numeric" : "text"}
          autoComplete="one-time-code"
          required
          maxLength={factorKind === "totp" ? 32 : 64}
          aria-describedby={credentialError ? "totp-replacement-feedback" : undefined}
          value={factorCode}
          onChange={(event) => setFactorCode(event.target.value)}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Preparando…" : "Preparar factor nuevo"}
        </button>
      </form>
      {feedback ? <p id="totp-replacement-feedback" role="alert">{feedback}</p> : null}
      {setup ? (
        <div className="totp-setup" aria-labelledby="totp-replacement-setup-title">
          <h3 id="totp-replacement-setup-title">Configura la nueva aplicación</h3>
          <p>
            Escanea este código QR o ingresa la clave manual. El factor anterior, tus
            códigos de recuperación y esta sesión siguen activos hasta confirmar la nueva configuración.
          </p>
          <QRCodeSVG
            aria-label="Código QR para configurar la nueva aplicación de autenticación"
            role="img"
            size={220}
            value={setup.provisioningUri}
          />
          <p>Clave manual</p>
          <output className="totp-setup__manual-key" aria-label="Clave manual de autenticación">
            {setup.manualKey.match(/.{1,4}/g)?.join(" ")}
          </output>
          <p>La configuración pendiente vence después de 30 minutos.</p>
          <form className="staff-access-form" onSubmit={(event) => void confirm(event)}>
            <label htmlFor="replace-totp-confirmation-code">Código de la nueva aplicación</label>
            <input
              id="replace-totp-confirmation-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              maxLength={32}
              value={confirmationCode}
              onChange={(event) => setConfirmationCode(event.target.value)}
            />
            <button type="submit" disabled={submitting}>
              {submitting ? "Confirmando…" : "Confirmar y reemplazar factor"}
            </button>
          </form>
        </div>
      ) : null}
    </section>
  );
}
