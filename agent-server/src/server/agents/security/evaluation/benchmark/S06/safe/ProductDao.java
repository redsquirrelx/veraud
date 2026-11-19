import java.sql.*;

public class ProductDao {
    public ResultSet find(Connection conn, int id) throws SQLException {
        PreparedStatement ps = conn.prepareStatement("SELECT * FROM products WHERE id = ?");
        ps.setInt(1, id);
        return ps.executeQuery();
    }
}
