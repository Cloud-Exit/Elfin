// Helper to handle authenticated requests and automatically logout on 401

export async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem('token')
  const headers = {
    ...options.headers,
    ...(token ? { Authorization: `Bearer ${token}` } : {})
  }

  const res = await fetch(url, { ...options, headers })
  
  if (res.status === 401) {
    localStorage.removeItem('token')
    window.location.href = '/'
  }
  
  return res
}
