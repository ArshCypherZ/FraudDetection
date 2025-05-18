// Temporary debug file to test transactions display
console.log("Starting transaction debug script");

// Try to get current user token
const token = localStorage.getItem('accessToken');
const userId = localStorage.getItem('userId');

console.log("User is logged in:", !!token);

if (token) {
  // Directly call the API
  fetch('http://localhost:8000/api/transactions?limit=10', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  })
  .then(response => {
    console.log("API Response status:", response.status);
    return response.json();
  })
  .then(data => {
    console.log("Transactions from API:", data);
    if (Array.isArray(data)) {
      console.log("Number of transactions:", data.length);
    } else {
      console.log("API didn't return an array");
    }
  })
  .catch(error => {
    console.error("Error fetching transactions:", error);
  });

  // Check if the table exists
  const tbody = document.getElementById('transactionsTableBody');
  console.log("Transaction table body exists:", !!tbody);
  if (tbody) {
    console.log("Current table content:", tbody.innerHTML);
  }
}
