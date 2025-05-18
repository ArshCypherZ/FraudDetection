// Authentication helper functions
const API_BASE_URL = 'http://localhost:8000';

// Login function that properly handles OAuth2 form-data requests
async function loginUser(username, password) {
  try {
    // OAuth2 requires form data, not JSON
    const formData = new FormData();
    formData.append('username', username);
    formData.append('password', password);
    
    const response = await fetch(`${API_BASE_URL}/token`, {
      method: 'POST',
      body: formData
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Login failed');
    }
    
    const tokenData = await response.json();
    
    // Save token in local storage
    localStorage.setItem('accessToken', tokenData.access_token);
    localStorage.setItem('userId', tokenData.user_id);
    localStorage.setItem('username', tokenData.username);
    
    return tokenData;
  } catch (error) {
    console.error('Login error:', error);
    throw error;
  }
}

// Register a new user
async function registerUser(username, password, email, fullName) {
  try {
    const response = await fetch(`${API_BASE_URL}/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ 
        username, 
        password, 
        email, 
        full_name: fullName || (email ? email.split('@')[0] : username)
      })
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Registration failed');
    }
    
    return await response.json();
  } catch (error) {
    console.error('Registration error:', error);
    throw error;
  }
}

// Get user profile with authentication
async function getUserProfile() {
  try {
    const token = localStorage.getItem('accessToken');
    if (!token) {
      throw new Error('No authentication token found');
    }
    
    const response = await fetch(`${API_BASE_URL}/users/me`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (!response.ok) {
      throw new Error('Failed to fetch user profile');
    }
    
    return await response.json();
  } catch (error) {
    console.error('Get profile error:', error);
    throw error;
  }
}

// Add authorization header to any API call
async function fetchWithAuth(url, options = {}) {
  const token = localStorage.getItem('accessToken');
  if (!token) {
    throw new Error('No authentication token found');
  }
  
  const authOptions = {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${token}`
    }
  };
  
  return fetch(url, authOptions);
}

// Check if user is already authenticated
function isAuthenticated() {
  return !!localStorage.getItem('accessToken');
}

// Logout user
function logoutUser() {
  localStorage.removeItem('accessToken');
  localStorage.removeItem('userId');
  localStorage.removeItem('username');
}
