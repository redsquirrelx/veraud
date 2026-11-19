function getOrder(db, req) {
  return db.query("SELECT * FROM orders WHERE id = " + req.params.id.trim());
}
module.exports = { getOrder };
