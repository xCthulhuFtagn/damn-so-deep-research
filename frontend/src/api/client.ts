import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Create axios instance
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('access_token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor to handle auth errors
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear token and redirect to login
      localStorage.removeItem('access_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default apiClient;

// Auth API
export const authApi = {
  login: async (username: string, password: string) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    const response = await apiClient.post('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return response.data;
  },

  register: async (username: string, password: string) => {
    const response = await apiClient.post('/auth/register', { username, password });
    return response.data;
  },

  getMe: async () => {
    const response = await apiClient.get('/auth/me');
    return response.data;
  },
};

// Runs API
export const runsApi = {
  list: async () => {
    const response = await apiClient.get('/runs');
    return response.data;
  },

  create: async (title: string) => {
    const response = await apiClient.post('/runs', { title });
    return response.data;
  },

  get: async (runId: string) => {
    const response = await apiClient.get(`/runs/${runId}`);
    return response.data;
  },

  update: async (runId: string, data: { title?: string; status?: string }) => {
    const response = await apiClient.patch(`/runs/${runId}`, data);
    return response.data;
  },

  delete: async (runId: string) => {
    await apiClient.delete(`/runs/${runId}`);
  },
};

// Research API
export const researchApi = {
  start: async (runId: string, message?: string) => {
    const response = await apiClient.post('/research/start', { run_id: runId, message });
    return response.data;
  },

  pause: async (runId: string) => {
    const response = await apiClient.post('/research/pause', { run_id: runId });
    return response.data;
  },

  sendMessage: async (runId: string, message: string) => {
    const response = await apiClient.post('/research/message', { run_id: runId, message });
    return response.data;
  },

  getState: async (runId: string) => {
    const response = await apiClient.get(`/research/state/${runId}`);
    return response.data;
  },
};

// Approvals API
export const approvalsApi = {
  getPending: async (runId: string) => {
    const response = await apiClient.get(`/approvals/${runId}`);
    return response.data;
  },

  respond: async (runId: string, commandHash: string, approved: boolean) => {
    const response = await apiClient.post(`/approvals/${runId}/${commandHash}`, { approved });
    return response.data;
  },
};
