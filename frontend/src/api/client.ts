import createClient from "openapi-fetch";
import type { paths } from "./openapi.generated";

export const api = createClient<paths>({
  baseUrl: "",
  credentials: "same-origin",
});
