// static/cart.js

// Function to calculate total quantity in the cart from local storage
function calculateCartTotalQuantity() {
    const currentOrder = JSON.parse(localStorage.getItem('cosmicOrder')) || [];
    // Sum the quantity of each item in the order, defaulting quantity to 0 if missing
    const totalQuantity = currentOrder.reduce((sum, item) => sum + (item.quantity || 0), 0);
    return totalQuantity;
}

// Function to update the cart count display in the header
function updateCartCountDisplay() {
    const cartCountSpan = document.getElementById('cart-count');
    if (cartCountSpan) {
        const totalQuantity = calculateCartTotalQuantity();
        cartCountSpan.textContent = totalQuantity.toString();
    }
}

// Update the cart count when the page loads
document.addEventListener('DOMContentLoaded', () => {
    updateCartCountDisplay();
});

// Note: Specific cart manipulation functions (add, remove, quantity change)
// and page-specific display logic should remain in their respective files
// (menu.js, order.js, custom_pizza.js or within script tags) but should call
// updateCartCountDisplay() after changing the cart data in local storage.