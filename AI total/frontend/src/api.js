import '../../ui/api-routes.js';
import '../../ui/api-client.js';
export const {api, request, configure, APIError} = globalThis.TrainingAPI;

/* Attach a JWT to every subsequent API call (Этап 5: ролевой доступ). */
export function attachToken(token) {
  if (token) configure({token});
}
