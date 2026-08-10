export function requestError(operation: string, status: number): Error {
  return new Error(`${operation}请求失败 (${status})`);
}
