import java.sql.*;

public class UserDao {
    public ResultSet find(Connection conn, String name) throws SQLException {
        Statement stmt = conn.createStatement();
        return stmt.executeQuery("SELECT * FROM users WHERE name = '" + name.trim() + "'");
    }
}
