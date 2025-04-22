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

    // --- ADD THIS SECTION ---
    const addToOrderButtons = document.querySelectorAll('.add-to-order-btn');
    addToOrderButtons.forEach(button => {
        button.addEventListener('click', function() {
            const itemId = this.dataset.id;
            const itemName = this.dataset.name;
            const itemDescription = this.dataset.description;
            const itemPrice = parseFloat(this.dataset.price);
            const itemCategory = this.dataset.category;
            const itemDietary = this.dataset.dietary;
            const itemCustomizable = this.dataset.customizable === 'true';

            // --- Your cart logic here (example) ---
            let currentOrder = JSON.parse(localStorage.getItem('cosmicOrder')) || [];
            const existingItemIndex = currentOrder.findIndex(item => item.id === itemId);

            if (existingItemIndex > -1) {
                // Item already in cart, increase quantity
                currentOrder[existingItemIndex].quantity += 1;
            } else {
                // Item not in cart, add it
                currentOrder.push({
                    id: itemId,
                    name: itemName,
                    description: itemDescription,
                    price: itemPrice,
                    category: itemCategory,
                    dietary: itemDietary,
                    customizable: itemCustomizable,
                    quantity: 1
                });
            }

            localStorage.setItem('cosmicOrder', JSON.stringify(currentOrder));
            updateCartCountDisplay(); // Update the cart count in the header
            console.log(`Added to cart: ${itemName}`);
        });
    });
    // --- END ADD THIS SECTION ---
});

// Note: Specific cart manipulation functions (add, remove, quantity change)
// and page-specific display logic should remain in their respective files
// (menu.js, order.js, custom_pizza.js or within script tags) but should call
// updateCartCountDisplay() after changing the cart data in local storage.