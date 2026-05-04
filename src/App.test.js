import { render, screen } from "@testing-library/react";
import SearchForm from "./components/SearchForm";

test("renders scanner filters and submit action", () => {
  render(<SearchForm onSearch={jest.fn()} />);

  expect(screen.getByText(/Scanner Filters/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/Min Price/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/Max RSI/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Search Stocks/i })).toBeInTheDocument();
});
