import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const CartContext = createContext(null);
const STORAGE_KEY = 'partsCart';

export function CartProvider({ children }) {
  const [items, setItems] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });

  // BC quote state (session-only, not persisted)
  const [bcQuoteId, setBcQuoteId] = useState(null);
  const [bcQuoteNumber, setBcQuoteNumber] = useState(null);
  const [quotePricing, setQuotePricing] = useState(null);

  // Persist items to localStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  }, [items]);

  // Clear quote when items change (cart no longer matches)
  const clearQuote = useCallback(() => {
    setBcQuoteId(null);
    setBcQuoteNumber(null);
    setQuotePricing(null);
  }, []);

  const addItem = useCallback((item) => {
    clearQuote();
    setItems(prev => {
      const existing = prev.findIndex(i => i.item_number === item.item_number);
      if (existing >= 0) {
        const updated = [...prev];
        updated[existing] = {
          ...updated[existing],
          quantity: updated[existing].quantity + (item.quantity || 1),
        };
        return updated;
      }
      return [...prev, { ...item, quantity: item.quantity || 1 }];
    });
  }, [clearQuote]);

  const addItems = useCallback((newItems) => {
    clearQuote();
    setItems(prev => {
      const updated = [...prev];
      for (const item of newItems) {
        const existing = updated.findIndex(i => i.item_number === item.item_number);
        if (existing >= 0) {
          updated[existing] = {
            ...updated[existing],
            quantity: updated[existing].quantity + (item.quantity || 1),
          };
        } else {
          updated.push({ ...item, quantity: item.quantity || 1 });
        }
      }
      return updated;
    });
  }, [clearQuote]);

  const removeItem = useCallback((item_number) => {
    clearQuote();
    setItems(prev => prev.filter(i => i.item_number !== item_number));
  }, [clearQuote]);

  const updateQuantity = useCallback((item_number, quantity) => {
    clearQuote();
    if (quantity <= 0) {
      setItems(prev => prev.filter(i => i.item_number !== item_number));
    } else {
      setItems(prev => prev.map(i =>
        i.item_number === item_number ? { ...i, quantity } : i
      ));
    }
  }, [clearQuote]);

  const clearCart = useCallback(() => {
    clearQuote();
    setItems([]);
  }, [clearQuote]);

  const setQuoteResult = useCallback((result) => {
    setBcQuoteId(result.bc_quote_id);
    setBcQuoteNumber(result.bc_quote_number);
    setQuotePricing(result.pricing);
  }, []);

  const value = {
    items,
    itemCount: items.reduce((sum, i) => sum + i.quantity, 0),
    bcQuoteId,
    bcQuoteNumber,
    quotePricing,
    addItem,
    addItems,
    removeItem,
    updateQuantity,
    clearCart,
    clearQuote,
    setQuoteResult,
  };

  return (
    <CartContext.Provider value={value}>
      {children}
    </CartContext.Provider>
  );
}

export function useCart() {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error('useCart must be used within CartProvider');
  return ctx;
}
